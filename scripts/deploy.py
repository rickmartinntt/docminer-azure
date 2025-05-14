#!/usr/bin/env python3
import json, os, subprocess, sys, pathlib

cfg_path = pathlib.Path("src/function_app/local.settings.json")
with cfg_path.open() as f:
    values = json.load(f)["Values"]

os.environ.update(
    RESOURCE_GROUP  = values["RESOURCE_GROUP"],
    FUNCTION_APP    = values["FUNCTION_APP"],
    SUBSCRIPTION_ID = values["SUBSCRIPTION_ID"],
)

print(f"Deploying {values['FUNCTION_APP']} in {values['RESOURCE_GROUP']} …")
subprocess.check_call([sys.executable, "src/deploy/deploy.py"] + sys.argv[1:])
