#!/bin/bash
# A script to generate crab config file automaticly

# project config
dataList='dataList.txt'
pset='PSet.py'
output='mymultilep.root'
outdir='/store/user/qinju/X3872'
storage_site='T3_CH_CERNBOX' #T3_CH_CERNBOX or so
lumi_mask='Cert_Collisions2022_355100_362760_Golden.json'

cat $dataList | while read row
do
	# tag1,2,3 are tags from CMS data naming standard
	# tag1: physics target, tag2: data set, tag3: data format
	data=$(echo $row  | awk 'BEGIN{FS=" "} {print $1}')
	tag1=$(echo $data | awk 'BEGIN{FS="/"} {print $2}')
	tag2=$(echo $data | awk 'BEGIN{FS="/"} {print $3}')
	tag3=$(echo $data | awk 'BEGIN{FS="/"} {print $4}')
	# Tag Format
	# define tag format with varibale tag, it will show up at TaskTag in the config .py files and also in their filenames 
	tag1_=$(echo $tag1 | grep -o [0-9]) 
	tag2_=$(echo $tag2 | awk 'BEGIN{FS="-"} {print $1$3}')
	tag=${tag1_}_${tag2_}_$tag3

	# check and create pset.py according to global tag
	sed -e 's:/DATASET/:'"${data}:" crab3_template.py > ${tag}.py
	sed -i -e 's:/TASK_TAG/:'"${tag}:" -e 's:/PSET/:'"${pset}:" ${tag}.py
	sed -i -e 's:/OUTPUT/:'"${output}:" -e 's:/OUTDIR/:'"${outdir}:" ${tag}.py
	sed -i -e 's:/STORAGE/:'"${storage_site}:" -e 's:/LUMI_MASK/:'"${lumi_mask}:" ${tag}.py
done
