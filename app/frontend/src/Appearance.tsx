import {createContext,useContext,useEffect,useLayoutEffect,useState,ReactNode} from 'react';
import {Moon,Sun,Monitor} from 'lucide-react';

type Appearance='system'|'dark'|'light';
const storageKey='shansuan.appearance';
const choices=[['system','跟随系统',Monitor],['dark','深色',Moon],['light','浅色',Sun]] as const;
function readAppearance():Appearance{
  try{const value=localStorage.getItem(storageKey);if(value==='dark'||value==='light')return value;}catch{/* Appearance remains usable when browser storage is unavailable. */}
  return 'system';
}
const AppearanceContext=createContext<{value:Appearance,setValue:(value:Appearance)=>void}>({value:'system',setValue:()=>{}});

export function AppearanceProvider({children}:{children:ReactNode}){
  const [value,setValue]=useState<Appearance>(readAppearance);
  const [systemDark,setSystemDark]=useState(()=>matchMedia('(prefers-color-scheme: dark)').matches);
  useEffect(()=>{
    const media=matchMedia('(prefers-color-scheme: dark)');
    const update=()=>setSystemDark(media.matches);
    const sync=(event:StorageEvent)=>{if(event.key===storageKey||event.key===null)setValue(readAppearance())};
    media.addEventListener('change',update);window.addEventListener('storage',sync);update();
    return()=>{media.removeEventListener('change',update);window.removeEventListener('storage',sync)};
  },[]);
  useLayoutEffect(()=>{
    const root=document.documentElement;
    const resolved=value==='system'?(systemDark?'dark':'light'):value;
    root.dataset.theme=resolved;
    root.dataset.appearance=value;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content',resolved==='dark'?'#111321':'#eef3fa');
  },[value,systemDark]);
  const change=(next:Appearance)=>{
    setValue(next);
    try{localStorage.setItem(storageKey,next)}catch{/* No health data is stored in browser preferences. */}
  };
  return <AppearanceContext.Provider value={{value,setValue:change}}>{children}</AppearanceContext.Provider>;
}

export function AppearanceControl(){
  const {value,setValue}=useContext(AppearanceContext);
  return <fieldset className="appearance-control" aria-label="外观"><legend>外观</legend><div className="appearance-options">{choices.map(([key,label,Icon])=><button type="button" key={key} title={label} aria-label={'使用'+label+'外观'} aria-pressed={value===key} onClick={()=>setValue(key)}><Icon size={15}/><span>{label}</span></button>)}</div></fieldset>;
}
