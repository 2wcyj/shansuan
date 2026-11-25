'use strict';

function buildNetlifyHeaders(apiBase){
 let api;
 try{api=new URL(apiBase)}catch{throw new Error('VITE_API_BASE_URL must be a full HTTPS API origin')}
 if(api.protocol!=='https:'||api.username||api.password||api.pathname!=='/'||api.search||api.hash){
  throw new Error('VITE_API_BASE_URL must be a full HTTPS API origin without credentials, path, query, or fragment');
 }
 const policy=[
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' blob: data: "+api.origin,
  "connect-src 'self' "+api.origin,
  "font-src 'self'",
  "manifest-src 'self'",
  "worker-src 'self' blob:",
  "media-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'self'",
  "frame-ancestors 'none'"
 ].join('; ');
 return '/*\n  Content-Security-Policy: '+policy+'\n';
}

if(require.main===module){
 const fs=require('node:fs');
 const path=require('node:path');
 const apiBase=process.env.VITE_API_BASE_URL;
 const output=path.resolve(__dirname,'../dist/_headers');
 try{
  const content=buildNetlifyHeaders(apiBase);
  fs.mkdirSync(path.dirname(output),{recursive:true});
  fs.writeFileSync(output,content,{encoding:'utf8',mode:0o644});
  console.log('Wrote API-scoped Netlify CSP headers.');
 }catch(error){console.error(error.message);process.exitCode=1}
}

module.exports={buildNetlifyHeaders};
