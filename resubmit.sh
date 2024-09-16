#!/bin/bash
files='crab_crab3_6_*'
#for i in $files
#do
	#echo -e "\033[32m $i \033[0m"
	#crab status $i | sed -n -e '/jobs failed/p' > tmp_report.out
	cat report.out > tmp_report.out
	cat tmp_report.out | while read rows
	do	
		result=$(echo $rows | grep 'MINIAOD')
		if [[ $result != '' ]]
		then
			i=$rows
			#echo -e "\033[32m $i \033[0m"
		fi
		result1=$(echo $rows | grep '50664')
		if [[ $result1 != '' ]]
		then
			num=$(echo $result1 | awk '{print $1}')
			num=$(expr $num)
			if [[ $num -lt 100 ]]
			then
				echo -e "\033[32m $i \033[0m resubmit because $num 50664 failure"
				crab --quiet resubmit $i
			fi
		fi
	done 
	rm -f tmp_report.out
#done
