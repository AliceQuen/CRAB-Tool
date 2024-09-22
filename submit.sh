#!/bin/bash
dryRun=1 # 1 means only show jobs to be submitted but not actually resubmit; 0 means do submit
cfg=$(grep -o "'.*.py'" crab3_template.py | grep -o "[^'].*[^']")
for i in *.py
do
	if [[ $i != 'crab3_template.py' && $i != $cfg ]]
	then
		echo $i
		if [[ $dryRun != 1 ]]
		then
			crab --quiet submit $i
		fi
	fi
done
