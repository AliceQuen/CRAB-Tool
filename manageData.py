import json
import os
import sys
import argparse
import re

parser = argparse.ArgumentParser(description='CRAB Job manage tool')
parser.add_argument('mode', type=str, help='work mode, submit for first submit; status for checking status; resubmit for resubmit; kill to kill and reset job')
parser.add_argument('-y', '--year', type=str, help='years to be operated, seperated with comma')
parser.add_argument('-e', '--era', type=str, help='eras to be operated, seperated with comma')
parser.add_argument('-d', '--dataset', type=str, help='datasets to be operated, seperated with comma')
parser.add_argument('-n', '--name', type=str, help='job names to be operated, seperated with comma')
parser.add_argument('-E', '--error', type=str, help='errors to be resubmited, seperated with comma')
parser.add_argument('-v', '--verbose', action='store_true', help='verbose output with detailed error information (must be used with --name)')
args = parser.parse_args()

# chose mode
if not args.mode in ['submit', 'status', 'resubmit', 'kill']:
    print('invalid mode')
    exit()
# verbose validation
if args.verbose and args.mode != 'status':
    print('--verbose can only be used in status mode')
    exit()
if args.verbose and not args.name:
    print('--verbose must be used with --name, specify exactly one job name')
    exit()
if args.verbose and len(args.name.strip().split(',')) != 1:
    print('--verbose can only be used with exactly one job name when --verbose is enabled')
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
# initialize status statistics for status mode
if args.mode == 'status' and not args.verbose:
    status_stats = {}
    total_jobs = len(jobs_used)
for i in jobs_used:
        # lookingup config
        i = i.strip()
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
        singularity =''
        tail = ''
        if CMSSW['architecture'] == 'cmssw7':
            singularity = 'cmssw-el7 --command-to-run \"cmsenv;'
            tail = '\"'
        else:
            singularity = 'cmsenv;'
            tali = ''
        os.chdir(f"{homedir}/{CMSSW['release']}/src/{config['analysor_prefix']}/{analysor}/test/CRAB-Tool_{y}")
        if args.mode == 'submit':
            # submit
            if i[2] == 'unsubmitted':
                print(f"\033[32m submiting\033[0m {i[1]}")
                os.system(f"{singularity}crab --quiet submit crab3_{i[1]}.py{tail}")
                # update status
                os.system(f"sed -i -e /{i[1]}/s/unsubmitted/submitted/ {cwd}/joblist.o")
            else:
                print(f"{i[1]} \033[31m already submitted\033[0m")
        elif args.mode == 'status':
            # status
            if i[2] == 'unsubmitted':
                main_status = 'unsubmitted'
                if main_status in status_stats:
                        status_stats[main_status] += 1
                else:
                        status_stats[main_status] = 1
                print(f'job {i[1]} \033[31m not submitted\033[0m, please submit it first')
            else:
                if args.verbose:
                    print(f"\033[32m checking status with verbose errors for \033[0m {i[1]}")
                    os.system(f"{singularity}crab status --verboseErrors crab_{i[1]}{tail}")
                else:
                    print(f"\033[32m checking status for \033[0m {i[1]}")
                    os.system(f"{singularity}crab status crab_{i[1]} > temp1.o{tail}")
                    os.system("cat temp1.o | grep -e 'Status on' -e 'jobs failed with' > temp.o")
                    with open('temp.o', 'r') as file:
                        report = file.readlines()
                    status = list()
                    for x in report:
                        y = x
                        x = x.replace('\n', '').replace('\t', '')
                        x = x.strip()
                        x = x.split(' ')
                        status_line = re.search('Status on', y)
                        error_line = re.search('failed', y)
                        if status_line:
                            status.append(x[-1].split(':')[-1] + ':')
                        elif error_line:
                            status.append('error' + x[-1] + ':')
                    status = ''.join(status).strip('\t')
                    status = status.strip()
                    if status == '':
                        status = 'submitted'
                    print(f"Status is {status}")
                    os.system('rm temp.o temp1.o')
                    # update status
                    os.system(f"sed -i -e /{i[1]}/s/{i[2]}/{status}/ {cwd}/joblist.o")
                    # collect status statistics
                    # extract main status (first token before any colon)
                    main_status = status.split(':')[1] if ':' in status else status
                    main_status = main_status.strip()
                    if main_status in status_stats:
                        status_stats[main_status] += 1
                    else:
                        status_stats[main_status] = 1
        elif args.mode == 'resubmit':
            # resubmit
            match = re.search('error', i[2])
            error_hit = list()
            if match:
                Es = i[2].split(":")
                for x in Es:
                    match = re.search('error(.*)', x)
                    if match:
                        if error:
                            if match.group(1) in error.split(','):
                                error_hit.append(match.group(1))
                        else:
                            error_hit.append(match.group(1))
                if len(error_hit):
                    print(f"\033[32m resubmitting \033[0m {i[1]} because of error codes {error_hit}")
                    os.system(f"{singularity}crab --quiet resubmit crab_{i[1]}{tail}")
                    # update status
                    os.system(f"sed -i -e /{i[1]}/s/{i[2]}/resubmitted/ {cwd}/joblist.o")
                else:
                    print(f"\033[31m no error hit, nothing done for\033[0m {i[1]}, status is {i[2]}")
            else:
                print(f"\033[31m nothing done for \033[0m {i[1]}, status is {i[2]}")
        elif args.mode == 'kill':
            # kill and reset job
            if i[2] != 'unsubmitted':
                print(f"\033[32m killing \033[0m {i[1]}")
                os.system(f"{singularity}crab --quiet kill crab_{i[1]}{tail}")
                print(f"\033[32m deleting \033[0m crab_{i[1]} directory")
                os.system(f"rm -rf crab_{i[1]}")
                # update status to unsubmitted
                os.system(f"sed -i -e /{i[1]}/s/{i[2]}/unsubmitted/ {cwd}/joblist.o")
                print(f"\033[32m {i[1]} \033[0mhas been reset to unsubmitted")
            else:
                print(f"{i[1]} \033[31m is already unsubmitted\033[0m")

# print status statistics for status mode (non-verbose)
if args.mode == 'status' and not args.verbose:
    print('\n\033[1m=== Status Statistics ===\033[0m')
    print(f'Total jobs checked: \033[1m{total_jobs}\033[0m')
    # sort by count descending
    sorted_status = sorted(status_stats.items(), key=lambda x: x[1], reverse=True)
    # color map for different status
    color_map = {
        'finished': '\033[32m',    # green
        'submitted': '\033[34m',   # blue
        'unsubmitted': '\033[33m', # yellow
        'resubmitted': '\033[35m', # purple
        'error': '\033[31m',       # red
        'failed': '\033[31m',      # red
    }
    default_color = '\033[37m'     # white
    for status_name, count in sorted_status:
        percentage = (count / total_jobs) * 100
        color = color_map.get(status_name.lower(), default_color)
        reset = '\033[0m'
        print(f'  {color}{status_name:12} {count:4d} jobs ({percentage:5.1f}%){reset}')
    print('\033[1m========================\033[0m\n')

os.chdir(f'{cwd}')
