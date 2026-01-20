import json
import os

os.system("voms-proxy-init -voms cms --valid 172:00")
# load the config json file
with open('config.json', 'r') as file:
    data = json.load(file)
# loop over all years in the config file
for year in data['years']:
    print(f"Registering data for year: {year}")
    os.system(f"das_client --query='dataset dataset=/EGamma/Run{year}-PromptReco-v1/MINIAOD' --limit=0 --json > EGamma_Run{year}.json")