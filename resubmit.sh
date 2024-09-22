#!/bin/bash
declare -a errorCoded

############################### Configuration #############################
dryRun=1 # 1 means only show jobs to be resubmitted but not actually resubmit; 0 means do resubmit
errorCode=('8001' '50064') # specific jobs with cerntain error codes you wants to resubmit
###########################################################################

rowsTemp=''
tac report.out > tmp_report.out
cat tmp_report.out | while read rows
do	
	result=$(echo $rows | grep 'MINIAOD')
	if [[ $result != '' ]]
	then
		rowsTemp=$rows
		info=$(echo $info | sed -e 's/.$//')
		if [[ $isResubmit == '1' ]]
		then
			if [[ $dryRun == '1' ]]
			then
				echo -e "\033[32m $rowsTemp \033[0m resubmit because $info"
			else
				echo -e "\033[32m $rowsTemp \033[0m resubmit because $info"
				crab --quiet resubmit $rows
			fi
			else
				echo -e "\033[32m $rowsTemp \033[0m nothing to be resubmited"
			fi
 			info=''
			result=''
			isResubmit=0
	fi
	for i in ${errorCode[@]}
	do
		result1=$(echo $rows | grep "$i")
		if [[ $result1 != '' ]]
		then
			isResubmit=1
			num=$(echo $result1 | awk '{print $1}')
			info="$info $num $i failure,"
		fi
	done
done 
rm -f tmp_report.out
