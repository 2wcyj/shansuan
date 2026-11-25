export function apiUrl(path:string,base=''):string {
 if(!path.startsWith('/')||path.startsWith('//')||path.includes('\\'))throw new Error('API path must be a root-relative path');
 const raw=base.trim();
 if(!raw)return '/api'+path;
 let target:URL;
 try{target=new URL(raw)}catch{throw new Error('VITE_API_BASE_URL must be an absolute HTTPS origin')}
 if(target.username||target.password)throw new Error('VITE_API_BASE_URL must not contain credentials');
 if(target.pathname!=='/'||target.search||target.hash)throw new Error('VITE_API_BASE_URL must be an origin only');
 const local=['localhost','127.0.0.1','[::1]'].includes(target.hostname);
 if(target.protocol!=='https:'&&!(local&&target.protocol==='http:'))throw new Error('VITE_API_BASE_URL must use HTTPS outside localhost');
 return target.origin+'/api'+path;
}

export function sessionUrl(base=''):string {
 return base.trim()?apiUrl('/auth/session',base):apiUrl('/session',base);
}

export function withApiCredentials(options:RequestInit={}):RequestInit {
 return {...options,credentials:'include'};
}
