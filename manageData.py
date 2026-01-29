import json
import os
import sys
import argparse
import re

parser = argparse.ArgumentParser(description='CRAB Job manage tool')
parser.add_argument('mode', type=str, help='work mode, submit for first submit; status for checking status; resubmit for resubmit')
parser.add_argument('-y', '--year', type=str, help='years to be operated, seperated with comma')
parser.add_argument('-e', '--era', type=str, help='eras to be operated, seperated with comma')
parser.add_argument('-d', '--dataset', type=str, help='datasets to be operated, seperated with comma')
parser.add_argument('-n', '--name', type=str, help='job names to be operated, seperated with comma')
parser.add_argument('-E', '--error', type=str, help='errors to be resubmited, seperated with comma')
args = parser.parse_args()

# chose mode
if not args.mode in ['submit', 'status', 'resubmit']:
    print('invalid mode')
    exit()
# open config and joblist
with open('config.json', 'r') as file:
    config = json.load(file)
with open('joblist.o', 'r') as file:
    jobs = file.readlines()
cwd = os.getcwd()
# decide jobs to operate
jobs_used = set()
years = set()
eras = set()
datasets = set()
names = set()
errors = set()
year = args.year
era = args.era
dataset = args.dataset
name = args.name
error = args.error
if not (year or era or dataset or name or error):
    print('no arguments inputted, all jobs will be operated')
    jobs_used = set(jobs)
else:
    if args.mode != 'resubmit' and (error):
        print('--error is set but not in resubmit mode, this will not affect')
    for i in jobs:
        i = i.strip()
        j = i.split(',')
        match = re.search('Run([0-9]+)([A-Z]{1})', j[0])
        # sort by year, eras, datasets, names
        if year:
            if match.group(1) in year.strip().split(','):
                years.add(i)
        if era:
            if match.group(2) in era.strip().split(','):
                eras.add(i)
        if dataset:
            if j[0].split('/')[1] in dataset.strip().split(','):
                datasets.add(i)
        if name:
            if j[1] in name.strip().split(','):
                names.add(i)
        job_ = list()
        if len(years):
            job_.append(years)
        if len(eras):
            job_.append(eras)
        if len(datasets):
            job_.append(datasets)
        if len(names):
            job_.append(names)
        if len(job_):
            jobs_used = job_[0]
            for x in job_:
                jobs_used = jobs_used & x
# process jobs
# find location
cwd = os.getcwd()
homedir = f"{config['home_dir']}"
analysor = f"{config['analysor']}".split('/')[-1]
print("jobs are:")
for i in jobs_used:
        # lookingup config
        i = i.split(',')
        y = re.search('Run([0-9]+)([A-Z]{1})', i[0]).group(1)
        y_in = False
        CMSSW = dict()
        for j in config['year_config']:
            if str(j['year']) == y:
                y_in = True
                CMSSW = j['CMSSW']
        if not y_in:
            print('year not found in config')
            exit()
        if CMSSW['architecture'] == 'cmssw7':
            os.system('cmssw7')
        os.chdir(f"{homedir}/{CMSSW['release']}/src/{config['analysor_prefix']}/{analysor}/test/CRAB-Tool_{y}")
        if args.mode == 'submit':
            # submit
            if i[2] == 'unsubmitted':
                print(f"\033[32m submiting\033[0m {i[1]}")
                os.system(f"crab --quiet submit crab3_{i[1]}.py")
                # update status
                os.system(f"sed -i -e /{i[1]}/s/unsubmitted/submitted/ {cwd}/joblist.o")
            else:
                print(f"{i[1]} \033[31m already submitted\033[0m")
        elif args.mode == 'status':
            # status
            if i[2] == 'unsubmitted':
                print(f'job {i[1]} not submitted, please submit it first')
            else:
                print(f"\033[32m checking status for \033[0m {i[1]}")
                os.system(f"crab status crab_{i[1]} | grep -e 'Status on the scheduler' -e 'jobs failed with' > temp.o")
                with open('temp.o', 'r') as file:
                    report = file.readlines()
                status = list()
                for x in report:
                    x = x.strip()
                    x = x.split(' ')
                    if x[1] == 'on':
                        status.append(x[-1].split(':')[-1] + ':')
                    elif x[1] == 'jobs':
                        status.append(x[-1] + ',')
                status = ''.join(status).strip('\t')
                status = re.sub(r'[^A-Z^a-z^0-9]+$', '', status)
                print(status)
                os.system('rm temp.o')
                print(f"sed -i -e /{i[1]}/s/{i[2]}/{status}/ {cwd}/joblist.o")
                # update status
                os.system(f"sed -i -e /{i[1]}/s/{i[2]}/{status}/ {cwd}/joblist.o")
        elif args.mode == 'resubmit':
            # resubmit
            match = re.search(':', i[2])
            error_hit = list()
            if match:
                Es = i[2].split(":")[-1].split(',')
                if error:
                    for x in Es:
                        if x in error.split(','):
                            error_hit.append(x)
                else:
                    error_hit = Es
                if len(error_hit):
                    print(f"\033[32m resubmitting \033[0m {i[1]} because of error codes {error_hit}")
                    os.system(f"crab --quiet resubmit crab_{i[1]}")
                    # update status
                    os.system(f"sed -i -e /{i[1]}/s/{i[2]}/resubmitted/ {cwd}/joblist.o")
                else:
                    print(f"\033[31m no error hit, nothing done for\033[0m {i[1]}, status is {i[2]}")
            else:
                print(f"\033[31m nothing done for \033[0m {i[1]}, status is {i[2]}")
os.chdir(f'{cwd}')
