'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const ts=require('../frontend/node_modules/typescript');
const sourcePath=path.resolve(__dirname,'../frontend/src/cloudApiConfig.ts');
assert(fs.existsSync(sourcePath),'missing cloud API configuration helper');
const js=ts.transpileModule(fs.readFileSync(sourcePath,'utf8'),{
 compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}
}).outputText;
const moduleObject={exports:{}};
new Function('exports','module',js)(moduleObject.exports,moduleObject);
const {apiUrl,withApiCredentials,sessionUrl}=moduleObject.exports;
const buildGuardPath=path.resolve(__dirname,'../frontend/scripts/netlify-env.cjs');
assert(fs.existsSync(buildGuardPath),'missing Netlify build safety check');
const {validateNetlifyEnv}=require(buildGuardPath);
const headersPath=path.resolve(__dirname,'../frontend/scripts/netlify-headers.cjs');
assert(fs.existsSync(headersPath),'missing API-scoped Netlify security headers');
const {buildNetlifyHeaders}=require(headersPath);

assert.equal(apiUrl('/profile'),'/api/profile','empty API base preserves local same-origin mode');
assert.equal(sessionUrl(''),'/api/session','local session bootstrap remains same-origin');
assert.equal(sessionUrl('', 'cloud'),'/api/auth/session','same-origin cloud still requires account authentication');
assert.equal(sessionUrl('https://api.example.cn'),'https://api.example.cn/api/auth/session',
 'cloud session bootstrap must use the cloud authentication endpoint');
assert.equal(apiUrl('/records?date=2026-10-20'),'/api/records?date=2026-10-20');
assert.equal(apiUrl('/profile','https://api.example.cn/'),'https://api.example.cn/api/profile');
assert.equal(apiUrl('/profile','http://localhost:8000'),'http://localhost:8000/api/profile');
assert.throws(()=>apiUrl('/profile','http://api.example.cn'),/HTTPS/);
assert.throws(()=>apiUrl('/profile','https://user:pass@api.example.cn'),/credentials/);
assert.throws(()=>apiUrl('/profile','https://api.example.cn/v1'),/origin only/);
assert.throws(()=>apiUrl('//evil.example/path','https://api.example.cn'),/root-relative path/);
assert.throws(()=>apiUrl('/profile','https://api.example.cn?token=secret'),/origin only/);

assert.deepEqual(withApiCredentials({method:'POST',cache:'no-store'}),{
 method:'POST',cache:'no-store',credentials:'include'
});
assert.deepEqual(validateNetlifyEnv({VITE_DEPLOY_PLATFORM:'local'}),{platform:'local'});
assert.throws(()=>validateNetlifyEnv({VITE_DEPLOY_PLATFORM:'netlify'}),/VITE_API_BASE_URL/);
const productionEnv={
 VITE_DEPLOY_PLATFORM:'netlify',
 VITE_API_BASE_URL:'https://api.example.cn',
 VITE_APP_ORIGIN:'https://app.example.cn',
 VITE_COOKIE_SITE_DOMAIN:'example.cn'
};
assert.deepEqual(validateNetlifyEnv(productionEnv),{
 platform:'netlify',apiOrigin:'https://api.example.cn',appOrigin:'https://app.example.cn',
 cookieSiteDomain:'example.cn'
});
assert.throws(()=>validateNetlifyEnv({...productionEnv,VITE_API_BASE_URL:'http://api.example.cn'}),/HTTPS/);
assert.throws(()=>validateNetlifyEnv({...productionEnv,VITE_API_BASE_URL:'https://other.cn'}),/same cookie site/);
assert.throws(()=>validateNetlifyEnv({...productionEnv,VITE_APP_ORIGIN:'https://app.netlify.app',VITE_API_BASE_URL:'https://api.netlify.app',VITE_COOKIE_SITE_DOMAIN:'netlify.app'}),/custom domain/);
const securityHeaders=buildNetlifyHeaders('https://api.example.cn');
assert(securityHeaders.includes("connect-src 'self' https://api.example.cn"));
assert(securityHeaders.includes("img-src 'self' blob: data: https://api.example.cn"));
assert(securityHeaders.includes("frame-ancestors 'none'"));
assert(!securityHeaders.includes('https://other.example'));
assert.throws(()=>buildNetlifyHeaders('http://api.example.cn'),/HTTPS/);
console.log('PASS API base URL validation, local compatibility, and credentialed requests');



