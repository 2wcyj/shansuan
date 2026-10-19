"""Build a locally signed Android APK using the verified offline toolchain."""
import os
from pathlib import Path
import secrets
import subprocess
import sys
import zipfile

# Keep the drive-letter path used to invoke this script.  The bundled Android
# tools are native Windows binaries and some versions cannot open Unicode
# paths; invoking through an ASCII drive alias (see the .cmd wrapper) avoids
# that limitation.  ``resolve()`` would dereference the alias back to the
# Chinese workspace path.
ROOT = Path(__file__).absolute().parents[2]
TOOLS = ROOT / '.tools/android'
ANDROID = ROOT / 'app/android'
BUILD = ANDROID / 'build'
OUTPUT = ROOT / '手机安装包' / '膳算-Android.apk'


def run(args, *, cwd=ROOT):
    command = [str(x) for x in args]
    if command[0].lower().endswith(('.bat', '.cmd')):
        subprocess.run(subprocess.list2cmdline(command), cwd=cwd, check=True, shell=True)
    else:
        subprocess.run(command, cwd=cwd, check=True)


def locate(root, name):
    matches = list(root.rglob(name))
    if not matches:
        raise FileNotFoundError(f'Android 构建工具缺失：{name}，请运行 prepare_android.py')
    return matches[0]


def main():
    jdk = locate(TOOLS / 'jdk', 'javac.exe').parent
    android_jar = locate(TOOLS / 'platform', 'android.jar')
    build_tools = locate(TOOLS / 'build-tools', 'aapt2.exe').parent
    aapt2, zipalign, apksigner = (build_tools / x for x in ('aapt2.exe', 'zipalign.exe', 'apksigner.bat'))
    BUILD.mkdir(parents=True, exist_ok=True); OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    resource_zip = BUILD / 'resources.zip'
    run([aapt2, 'compile', '--dir', ANDROID / 'res', '-o', resource_zip])
    base_apk = BUILD / 'base.apk'
    generated = BUILD / 'generated'
    run([aapt2, 'link', '-I', android_jar, '--min-sdk-version', '26', '--target-sdk-version', '35', '--manifest', ANDROID / 'AndroidManifest.xml',
         '--java', generated, '-o', base_apk, resource_zip])
    java = ANDROID / 'src/cn/shansuan/mobile/MainActivity.java'
    classes = BUILD / 'classes'; classes.mkdir(exist_ok=True)
    # Compile against the Android API while retaining the JDK runtime classes
    # needed by javac to lower Java 8 lambdas; D8 performs Android desugaring.
    run([jdk / 'javac.exe', '-encoding', 'UTF-8', '-source', '8', '-target', '8',
         '-classpath', android_jar, '-d', classes, java])
    dex = BUILD / 'dex'; dex.mkdir(exist_ok=True)
    env = {**os.environ, 'JAVA_HOME': str(jdk.parent), 'PATH': str(jdk) + os.pathsep + os.environ.get('PATH', '')}
    # apksigner.bat launches Java through the shell, so make the same JDK
    # visible to subsequent batch-tool invocations as well.
    os.environ.update({'JAVA_HOME': str(jdk.parent), 'PATH': env['PATH']})
    class_files = sorted(classes.rglob('*.class'))
    subprocess.run([str(jdk / 'java.exe'), '-cp', str(build_tools / 'lib/d8.jar'), 'com.android.tools.r8.D8',
         '--lib', str(android_jar), '--output', str(dex), *map(str, class_files)], cwd=ROOT, env=env, check=True)
    unsigned = BUILD / 'unsigned.apk'
    with zipfile.ZipFile(base_apk) as source, zipfile.ZipFile(unsigned, 'w', zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            if not item.filename.startswith('META-INF/'):
                target.writestr(item, source.read(item.filename))
        target.write(dex / 'classes.dex', 'classes.dex')
    aligned = BUILD / 'aligned.apk'
    run([zipalign, '-f', '4', unsigned, aligned])
    signing = TOOLS / 'signing'; signing.mkdir(exist_ok=True)
    keystore, password_file = signing / 'shansuan-local.keystore', signing / 'password.txt'
    if not keystore.exists():
        password = secrets.token_urlsafe(32)
        password_file.write_text(password, encoding='ascii')
        os.chmod(password_file, 0o600)
        run([jdk / 'keytool.exe', '-genkeypair', '-keystore', keystore, '-storepass', password,
             '-keypass', password, '-alias', 'shansuan-local', '-keyalg', 'RSA', '-keysize', '3072',
             '-validity', '3650', '-dname', 'CN=Shansuan Local App'])
    password = password_file.read_text(encoding='ascii')
    run([apksigner, 'sign', '--ks', keystore, '--ks-key-alias', 'shansuan-local',
         '--ks-pass', 'pass:' + password, '--key-pass', 'pass:' + password,
         '--out', OUTPUT, aligned])
    run([apksigner, 'verify', '--verbose', '--print-certs', OUTPUT])
    # aapt from older build-tools also has trouble with Unicode filenames;
    # inspect an ASCII-path copy while keeping the user-facing APK filename.
    inspect_apk = BUILD / 'verified.apk'
    inspect_apk.write_bytes(OUTPUT.read_bytes())
    run([locate(TOOLS / 'build-tools', 'aapt.exe'), 'dump', 'badging', inspect_apk])
    print(f'APK 已构建并校验：{OUTPUT}')


if __name__ == '__main__':
    main()
