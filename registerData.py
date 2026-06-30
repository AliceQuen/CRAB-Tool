import json
import os
import time
import sys
import argparse
import re

# load the config json file
with open(f'config.json', 'r') as file:
    config = json.load(file)
cwd = os.getcwd()
# naming
name_rule = [dict(), dict(), dict()]
for year in config['year_config']:
    y = str(year['year'])
    query = year['das_query']
    pattern = str(query).split('/')
    pattern.pop(0)
    os.system(f"das_client --query '{query}' > {y}.o")
    with open(f'{y}.o', 'r') as configlist:
        lines = configlist.readlines()
    for line in lines:
        line = line.strip()
        line = line.split('/')
        line.pop(0)
        names = list()
        for i in range(len(line)):
            regex_pattern = re.escape(pattern[i]).replace(r'\*', '(.*)')
            regex_pattern = f'^{regex_pattern}$'
            match = re.search(regex_pattern, line[i])
            if not match:
                print("No match pattern, this maybe related to the das query used")
                print("Excution Aborted")
                exit(1)
            for j in list(match.groups()):
                names.append(j)
            name = ''.join(names)
            if i == 1:
                name = f'{y}{name}'
            name_rule[i][f'{line[i]}'] = name
            names.clear()
    os.system(f'rm {y}.o')
name_rule = {
            "l1name" : name_rule[0],
            "l2name" : name_rule[1],
            "l3name" : name_rule[2]
        }
with open('naming.json', 'w') as file:
    json.dump(name_rule, file, indent=4)
print("The naming rule is auto generated, do you want to modify it?\n Please input 'n': don't modify 'y': modify")
while True:
    input_ = input('>>>')
    if input_ == 'n':
        break;
    elif input_ == 'y':
        replicated = True
        while replicated:
            os.system('vim naming.json')
            with open('naming.json', 'r') as file:
                naming = json.load(file)
            n = set()
            replicated = False
            for x in [1, 2, 3]:
                n.clear()
                for name_o, name_n in naming[f'l{x}name'].items():
                    n.add(name_n)
                if len(n) != len(naming[f'l{x}name'].items()):
                    print(f"\033[31m Names in l{x}name replicate!! Please check!!\033[0m")
                    replicated = True
                    time.sleep(2)
        print("\033[32m Modification success.\033[0m Do you still want to modify, if not, the config process will begin\n Please input 'n': don't modify 'y': modify")
    else:
        print("Please input 'n': don't modify 'y': modify")
# read naming.json for latter use
with open('naming.json', 'r') as file:
    name_rule = json.load(file)
# make CMSSW dirs
os.system(f"mkdir -p {config['home_dir']}")
os.chdir(f"{config['home_dir']}")
cmssws = dict()
analyzer_path = config['analyzer']
analyzer = config['analyzer'].split('/')[-1]
for year in config['year_config']:
    cmssws[year['CMSSW']['release']] = year['CMSSW']['architecture']
for realse, arch in cmssws.items():
    if arch == 'cmssw7':
        os.system(f'cmssw-el7 --command-to-run \"cmsrel {realse}\"')
    else:
        os.system(f"cmsrel {realse}")
    os.system(f"mkdir -p {realse}/src/{config['analyzer_prefix']}")
    is_git_repo = os.path.isdir(os.path.join(analyzer_path, '.git'))
    branch = config.get('analyzer_branch', '')
    use_clone = False
    if is_git_repo and branch:
        result = os.popen(f'cd {analyzer_path} && git branch -a').read()
        if branch in result:
            use_clone = True
    if use_clone:
        os.system(f"git clone -b {branch} {analyzer_path} {realse}/src/{config['analyzer_prefix']}/{analyzer}")
    else:
        os.system(f"cp -r {analyzer_path} {realse}/src/{config['analyzer_prefix']}")
    os.chdir(f"{realse}/src/{config['analyzer_prefix']}")
    if config.get('analyzer_sedcmd'):
        sed_cmd = config['analyzer_sedcmd']
        safe = True
        parts = sed_cmd.split()
        for p in parts:
            if os.path.isabs(p):
                safe = False
                break
        if '..' in sed_cmd:
            safe = False
        if safe:
            os.system(sed_cmd)
    if arch == 'cmssw7':
        os.system('cmssw-el7 --command-to-run \"cmsenv;scramv1 b\"')
    else:
        os.system('cmsenv;scramv1 b')
    os.chdir(f"{config['home_dir']}")
# creating job dir and configs
jobs = list()
job_type = config["job_type"]
for year in config['year_config']:
    #making crab tool directory
    y = str(year['year'])
    os.chdir(f"{year['CMSSW']['release']}/src/{config['analyzer_prefix']}/{analyzer}/test")
    os.system(f"mkdir -p CRAB-Tool_{y}")
    # copy lumimask
    os.system(f"cp {year['lumimask']} CRAB-Tool_{y}/")
    # creating cmssw configs 
    g_tags = year['global_tags']
    for i in g_tags:
        cmssw_config_file = config['CMSSW_config'].replace(r'.py', f"_{y}{''.join(i['era'])}.py")
        hlts = list()
        fils = list()
        hlt = ''
        fil = ''
        for j in config['HLT_config']:
            if y in list(j['years']):
                hlts.append(j['hlt'])
                fils.append(j['filter'])
        for j in range(len(hlts)):
            if j < len(hlts) - 1:
                hlt = f'{hlt}\\\"{hlts[j]}\\\", '
                fil = f'{fil}\\\"{fils[j]}\\\", '
            else:
                hlt = f'{hlt}\\\"{hlts[j]}\\\"'
                fil = f'{fil}\\\"{fils[j]}\\\"'
        hlts.clear()
        fils.clear()
        os.system(f"cp {config['CMSSW_config']} {cmssw_config_file}")

        os.system(f"sed -i -e \"s/GLOBAL_TAG/{i['tag']}/\" -e \'s/HLT/{hlt}/\' -e \'s/FILTER/{fil}/\' {cmssw_config_file}")
    # query config and create crab configs
    os.chdir(f'CRAB-Tool_{y}')
    query = year['das_query']
    y = year['year']
    os.system(f"das_client --query '{query}' > {y}.o")
    with open(f'{y}.o', 'r') as configlist:
        lines = configlist.readlines()
    os.system(f'rm {y}.o')
    
    for line in lines:
        line = line.strip()
        dataset = line
        line = line.split('/')
        line.pop(0)
        # find era if job_type is data
        if job_type == "data":
            regex_pattern = f'Run{y}'+ '([A-Z]{1})'
            era = re.search(regex_pattern, line[1]).group(1)
        else:
            era = "all"
        if len(g_tags) == 1:
            cmssw_config_file = config['CMSSW_config'].replace(r'.py', f"_{y}{g_tags[0]['era'][0]}.py") 
        else:
            for j in g_tags:
                if era in j['era']:
                    cmssw_config_file = config['CMSSW_config'].replace(r'.py', f"_{y}{''.join(j['era'])}.py") 
        # create crab config
        name_ = [name_rule['l1name'][line[0]], '_', name_rule['l2name'][line[1]], '_', name_rule['l3name'][line[2]]]
        task_name = ''.join(name_)
        task_name = re.sub(r'[^A-Z^a-z^0-9]+$', '', task_name)
        task_name = re.sub(r'^[^A-Z^a-z^0-9]+', '', task_name)
        lumimask = f"{year['lumimask']}"
        if lumimask != "":
            lumimask = lumimask.split('/')[-1]
            os.system(f'cp {cwd}/crab3_template.py crab3_{task_name}.py')
            os.system(f"sed -i -e 's>OUTPUT>{config['output']}>' -e 's>PSET>../{cmssw_config_file}>' -e 's>DATASET>{dataset}>' -e 's>TASK_TAG>{task_name}>' -e 's>LUMI_MASK>{lumimask}>' -e 's>OUTDIR>{config['outdir']}>' -e 's>STORAGE>{config['storage']}>' crab3_{task_name}.py")
        else:
            os.system(f"sed -i -e 's>OUTPUT>{config['output']}>' -e 's>PSET>../{cmssw_config_file}>' -e 's>DATASET>{dataset}>' -e 's>TASK_TAG>{task_name}>' -e '/LUMI_MASK/d' -e 's>OUTDIR>{config['outdir']}>' -e 's>STORAGE>{config['storage']}>' crab3_{task_name}.py")

        jobs.append(f"{y},{dataset},{task_name},unsubmitted")
    os.chdir(f"{config['home_dir']}")
os.chdir(f"{cwd}")
with open('joblist.o', 'w') as file:
    for i in jobs:
        file.write(str(i) + '\n')
