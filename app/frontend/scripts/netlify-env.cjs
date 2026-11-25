'use strict';

function origin(value,name){
 let parsed;
 try{parsed=new URL(value)}catch{throw new Error(name+' must be a full HTTPS origin')}
 if(parsed.protocol!=='https:'||parsed.username||parsed.password||parsed.pathname!=='/'||parsed.search||parsed.hash){
  throw new Error(name+' must be a full HTTPS origin without credentials, path, query, or fragment');
 }
 return parsed;
}

function validateNetlifyEnv(env=process.env){
 if(env.VITE_DEPLOY_PLATFORM!=='netlify')return {platform:'local'};
 if(!env.VITE_API_BASE_URL)throw new Error('Set VITE_API_BASE_URL in Netlify environment variables before deploying.');
 if(!env.VITE_APP_ORIGIN)throw new Error('Set VITE_APP_ORIGIN to the custom frontend HTTPS origin before deploying.');
 if(!env.VITE_COOKIE_SITE_DOMAIN)throw new Error('Set VITE_COOKIE_SITE_DOMAIN to the shared registered domain before deploying.');
 const api=origin(env.VITE_API_BASE_URL,'VITE_API_BASE_URL');
 const app=origin(env.VITE_APP_ORIGIN,'VITE_APP_ORIGIN');
 const site=env.VITE_COOKIE_SITE_DOMAIN.toLowerCase().replace(/^\.+|\.+$/g,'');
 if(!site||site.includes('/')||site.includes(':')||site.includes('*'))throw new Error('VITE_COOKIE_SITE_DOMAIN must be a domain suffix, without scheme or wildcard.');
 const within=host=>host===site||host.endsWith('.'+site);
 if(!within(api.hostname)||!within(app.hostname)||api.hostname===app.hostname){
  throw new Error('Frontend and API must use different hostnames within the same cookie site.');
 }
 if(app.hostname.endsWith('.netlify.app')||app.hostname==='netlify.app'){
  throw new Error('Configure the Netlify site with your custom domain before deploying the cloud app.');
 }
 return {platform:'netlify',apiOrigin:api.origin,appOrigin:app.origin,cookieSiteDomain:site};
}

if(require.main===module){
 try{validateNetlifyEnv();console.log('Netlify environment checks passed.')}
 catch(error){console.error(error.message);process.exitCode=1}
}

module.exports={validateNetlifyEnv};
