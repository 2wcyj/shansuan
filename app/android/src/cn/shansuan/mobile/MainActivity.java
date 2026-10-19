package cn.shansuan.mobile;

import android.app.Activity;
import android.Manifest;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.SslErrorHandler;
import android.net.http.SslError;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.PermissionRequest;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.InetAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.util.Locale;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

public final class MainActivity extends Activity {
    private static final int PICK_CONFIG = 17;
    private static final String KEY_ALIAS = "shansuan_mobile_pairing_v1";
    private WebView web;
    private TextView status;
    private ValueCallback<Uri[]> fileCallback;
    private PermissionRequest cameraRequest;
    private String baseUrl = "";
    private String fingerprint = "";
    private String token = "";

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        showSetup();
        readStored();
        if (!token.isEmpty()) connect();
    }

    private void showSetup() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(36, 56, 36, 36);
        TextView title = new TextView(this); title.setText("膳算"); title.setTextSize(32);
        root.addView(title);
        status = new TextView(this); status.setText("连接电脑上的个人资料。手机与电脑需连接同一 Wi-Fi。"); status.setTextSize(16);
        root.addView(status);
        Button importButton = new Button(this); importButton.setText("导入电脑连接文件");
        importButton.setOnClickListener(v -> pickConfig()); root.addView(importButton);
        Button clearButton = new Button(this); clearButton.setText("断开并清除此手机的连接");
        clearButton.setOnClickListener(v -> clearPairing()); root.addView(clearButton);
        setContentView(root);
    }

    private void pickConfig() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE); intent.setType("*/*");
        startActivityForResult(intent, PICK_CONFIG);
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == 18) {
            if (fileCallback != null) fileCallback.onReceiveValue(resultCode == RESULT_OK && data != null && data.getData() != null ? new Uri[]{data.getData()} : null);
            fileCallback = null; return;
        }
        if (requestCode != PICK_CONFIG || resultCode != RESULT_OK || data == null || data.getData() == null) return;
        try (InputStream input = getContentResolver().openInputStream(data.getData())) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096]; int count;
            while ((count = input.read(buffer)) != -1 && bytes.size() < 65536) bytes.write(buffer, 0, count);
            JSONObject config = new JSONObject(bytes.toString(StandardCharsets.UTF_8.name()));
            String url = config.getString("url"); URI parsed = URI.create(url);
            InetAddress address = InetAddress.getByName(parsed.getHost());
            byte[] ip = address.getAddress();
            boolean privateIp = ip.length == 4 && ((ip[0] & 255) == 10 || ((ip[0] & 255) == 192 && (ip[1] & 255) == 168) || ((ip[0] & 255) == 172 && (ip[1] & 255) >= 16 && (ip[1] & 255) <= 31));
            String importedToken = config.getString("token"), importedFingerprint = config.getString("fingerprint").toLowerCase(Locale.ROOT);
            if (!"https".equals(parsed.getScheme()) || parsed.getPort() != 18766 || !privateIp || parsed.getRawPath().length() > 1 || importedToken.length() < 64 || !importedFingerprint.matches("[0-9a-f]{64}")) throw new IllegalArgumentException("连接文件内容无效或不是局域网地址");
            baseUrl = url; token = importedToken; fingerprint = importedFingerprint;
            saveStored(); connect();
        } catch (Exception error) { Toast.makeText(this, "无法导入连接文件：" + error.getMessage(), Toast.LENGTH_LONG).show(); }
    }

    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        if (!store.containsAlias(KEY_ALIAS)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setRandomizedEncryptionRequired(true).build());
            generator.generateKey();
        }
        return ((KeyStore.SecretKeyEntry) store.getEntry(KEY_ALIAS, null)).getSecretKey();
    }

    private void saveStored() throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key());
        byte[] encrypted = cipher.doFinal(new JSONObject().put("url", baseUrl).put("token", token).put("fingerprint", fingerprint).toString().getBytes(StandardCharsets.UTF_8));
        getSharedPreferences("pairing", MODE_PRIVATE).edit().putString("iv", android.util.Base64.encodeToString(cipher.getIV(), android.util.Base64.NO_WRAP)).putString("payload", android.util.Base64.encodeToString(encrypted, android.util.Base64.NO_WRAP)).apply();
    }

    private void readStored() {
        try {
            android.content.SharedPreferences prefs = getSharedPreferences("pairing", MODE_PRIVATE);
            if (!prefs.contains("payload")) return;
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            byte[] iv = android.util.Base64.decode(prefs.getString("iv", ""), android.util.Base64.NO_WRAP);
            cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, iv));
            JSONObject saved = new JSONObject(new String(cipher.doFinal(android.util.Base64.decode(prefs.getString("payload", ""), android.util.Base64.NO_WRAP)), StandardCharsets.UTF_8));
            baseUrl = saved.getString("url"); token = saved.getString("token"); fingerprint = saved.getString("fingerprint");
        } catch (Exception error) { clearPairing(); }
    }

    private void connect() {
        if (token.isEmpty()) return;
        showWeb();
        CookieManager cookies = CookieManager.getInstance(); cookies.setAcceptCookie(true);
        cookies.setCookie(baseUrl, "shansuan_mobile=" + token + "; Secure; HttpOnly; SameSite=Strict; Path=/", value -> { cookies.flush(); web.post(() -> web.loadUrl(baseUrl)); });
    }

    private void showWeb() {
        web = new WebView(this); web.getSettings().setJavaScriptEnabled(true); web.getSettings().setDomStorageEnabled(false);
        web.getSettings().setAllowFileAccess(false); web.getSettings().setAllowContentAccess(true); web.getSettings().setMixedContentMode(android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) { return !request.getUrl().toString().startsWith(baseUrl); }
            @Override public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                try {
                    if (!error.getUrl().startsWith(baseUrl + "/") && !error.getUrl().equals(baseUrl)) { handler.cancel(); return; }
                    java.security.cert.X509Certificate certificate = error.getCertificate().getX509Certificate();
                    String actual = hex(MessageDigest.getInstance("SHA-256").digest(certificate.getEncoded()));
                    if (actual.equals(fingerprint)) handler.proceed(); else handler.cancel();
                } catch (Exception failure) { handler.cancel(); }
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                Intent pick = new Intent(Intent.ACTION_GET_CONTENT); pick.setType("image/*"); pick.addCategory(Intent.CATEGORY_OPENABLE);
                startActivityForResult(Intent.createChooser(pick, "选择或拍摄食物照片"), 18); return true;
            }
            @Override public void onPermissionRequest(PermissionRequest request) {
                if (!request.getOrigin().toString().startsWith(baseUrl) || request.getResources().length != 1 || !PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(request.getResources()[0])) { request.deny(); return; }
                if (checkSelfPermission(Manifest.permission.CAMERA) == android.content.pm.PackageManager.PERMISSION_GRANTED) request.grant(request.getResources());
                else { cameraRequest = request; requestPermissions(new String[]{Manifest.permission.CAMERA}, 19); }
            }
        });
        setContentView(web);
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == 19 && cameraRequest != null) {
            if (grantResults.length > 0 && grantResults[0] == android.content.pm.PackageManager.PERMISSION_GRANTED) cameraRequest.grant(cameraRequest.getResources());
            else cameraRequest.deny();
            cameraRequest = null;
        }
    }

    private static String hex(byte[] input) { StringBuilder result = new StringBuilder(); for (byte b : input) result.append(String.format(Locale.ROOT, "%02x", b & 255)); return result.toString(); }

    private void clearPairing() {
        if (web != null) { web.stopLoading(); web.clearCache(true); web.clearHistory(); web.destroy(); web = null; }
        CookieManager.getInstance().removeAllCookies(null); CookieManager.getInstance().flush();
        getSharedPreferences("pairing", MODE_PRIVATE).edit().clear().apply();
        try { KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null); store.deleteEntry(KEY_ALIAS); } catch (Exception ignored) { }
        baseUrl = ""; token = ""; fingerprint = ""; showSetup();
    }

    @Override public void onBackPressed() { if (web != null && web.canGoBack()) web.goBack(); else super.onBackPressed(); }
}
