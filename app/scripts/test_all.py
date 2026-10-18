"""Sequential complete suite; failure halts. No personal database is opened."""
from pathlib import Path
import json,os,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))

def main():
    from app.scripts.model_runtime import start
    start()
    output=ROOT/'.test-output';output.mkdir(exist_ok=True)
    deps=Path(os.environ['USERPROFILE'])/'.cache/codex-runtimes/codex-primary-runtime/dependencies'
    node=deps/'node/bin/node.exe';frontend=ROOT/'app/frontend'
    steps=[('backend',[sys.executable,'-m','pytest','app/tests','-q','--junitxml=.test-output/all-tests.xml'],ROOT),('typescript',[str(node),str(frontend/'node_modules/typescript/bin/tsc'),'-b'],frontend),('frontend-build',[str(node),str(frontend/'node_modules/vite/bin/vite.js'),'build'],frontend),('browser',[str(node),str(ROOT/'app/tests/browser.cjs')],ROOT)]
    results=[];env={**os.environ,'PYTHONUTF8':'1'}
    for name,cmd,cwd in steps:
        began=time.monotonic();r=subprocess.run(cmd,cwd=cwd,env=env)
        results.append({'stage':name,'exit_code':r.returncode,'seconds':round(time.monotonic()-began,2)})
        (output/'final-run.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
        if r.returncode:return r.returncode
    return 0
if __name__=='__main__':raise SystemExit(main())
