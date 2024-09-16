#!/bin/bash
run='Run2023'
t2=('Cv4' 'Dv2')
t4=('Cv2' 'Cv3')
#for i in *MINIAOD.py
#do
#	if_need=$(echo $i | awk 'BEGIN{FS="_"} {print $2}')
#	if [[ $if_need == '6' || $if_need == '7' ]]; then
#		sed -i -e 's:T3_CH_CERNBOX:T2_CN_Beijing:' $i
#		crab --quiet submit $i
#		echo $i
#	fi
#done
for i in ${t2[@]}
do
	rm -r "./crab_crab3_2_Run2023${i}_MINIAOD"
	crab --quiet submit "crab3_2_Run2023${i}_MINIAOD.py"
done
for i in ${t4[@]}
do
        rm -r "./crab_crab3_4_Run2023${i}_MINIAOD"
        crab --quiet submit "crab3_4_Run2023${i}_MINIAOD.py"
done  
