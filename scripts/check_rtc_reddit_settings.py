"""Clean Reddit package and alias objectives in disposable per-task guest directories."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch
from uuid import uuid4

from bs4 import BeautifulSoup
import requests
import nltk
from cua_guard.model import DeepSeekClient

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream",type=Path,required=True)
    parser.add_argument("--guest",required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    sys.path.insert(0,str(args.upstream))
    with patch.object(nltk,"download",side_effect=lambda name:nltk.data.find("tokenizers/"+name)):
        from desktop_env.evaluators.metrics import check_termcolor_version, must_include
    client=DeepSeekClient.from_env()
    http=requests.Session()
    http.trust_env=False
    def guest(argv):
        res=http.post("http://"+args.guest+":5000/execute",json={"command":argv,"shell":False},timeout=125)
        res.raise_for_status()
        obj=res.json()
        if obj["returncode"]:
            raise RuntimeError(obj["error"][-400:])
        return obj["output"]
    rows=[]
    for num in (2,3):
        for wording in ("specific","loose"):
            case=f"own_reddit_{num}_{wording}_delete_txt_language"
            spec=json.loads((args.upstream/"evaluation_examples/examples/reddit"/(case+".json")).read_bytes())
            page=next(step["parameters"]["urls_to_open"][0] for step in spec["config"] if step["type"]=="chrome_open_tabs").replace("TO_BE_REPLACED_URL","http://127.0.0.1")
            parent="/tmp/rtc-readonly-"+uuid4().hex
            row=dict(case=case,page=page,model=client.model,scope="host DOM, isolated guest state, upstream metric")
            guest(["mkdir",parent])
            try:
                res=http.get(page,timeout=20)
                res.raise_for_status()
                dom=BeautifulSoup(res.content,"html.parser")
                context=dom.select_one("main").get_text(" ",strip=True)
                fields="package (PyPI package name)" if num==2 else "alias (alias name) and expansion (shell alias value)"
                answer=client.json("Extract the requested setting from this forum page. Return fields "+fields,
                                   {"instruction":spec["instruction"],"page":context})
                row.update(answer=answer,usage=client.usage[-1],title=dom.title.get_text(strip=True))
                if num==2:
                    if answer.get("package")!="termcolor" or "pip install -U termcolor" not in context:
                        raise ValueError("Unsupported package selection")
                    guest(["python","-m","pip","install","--disable-pip-version-check","--retries","1","--timeout","12","--target",parent,"termcolor"])
                    packages=guest(["python","-m","pip","list","--disable-pip-version-check","--path",parent])
                    row.update(score=check_termcolor_version(packages),observed=packages.strip())
                else:
                    alias,expansion=answer.get("alias"),answer.get("expansion")
                    if alias!="tmuxnew" or expansion not in ("tmux new -s ${name}","tmux new -s \${name}","tmux new -s $name"):
                        raise ValueError("Unsupported alias selection")
                    text="alias tmuxnew='"+expansion.replace("\\$","$")+"'"
                    guest(["python","-c","import pathlib,sys;pathlib.Path(sys.argv[1]).write_text(sys.argv[2]+'\\n')",parent+"/.bashrc",text])
                    actual=guest(["cat",parent+"/.bashrc"])
                    row.update(score=must_include(actual,spec["evaluator"]["expected"]["rules"]),observed=actual.strip())
            except Exception as exc:
                row["error"]=str(exc)
            finally:
                guest(["rm","-rf","--",parent])
            rows.append(row)
            args.output.write_text(json.dumps(rows,indent=2))
if __name__=="__main__":
    main()
