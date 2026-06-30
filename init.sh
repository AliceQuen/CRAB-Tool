#!/bin/bash
if [[ $1 != '' ]]
then
	dir="Projects/$1"
	mkdir -p ${dir}
	cp registerData.py ${dir}
	cp manageData.py ${dir}
	cp crab3_template.py ${dir}
	cp config_template.json ${dir}/config.json
else
	echo -e "\033[31m error! no project name sepcified\033[0m"
fi
