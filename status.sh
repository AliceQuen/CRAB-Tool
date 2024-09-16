#!/bin/bash
rm -f report.out
echo '-------------------------** Crab Report **-------------------------' > report.out
for i in crab_crab3*
do
	sed -i -e '$a\'"${i}" report.out
	crab status $i | sed -n -e '/running/p' -e '/jobs failed/p' > tmp_report.out
	cat tmp_report.out | while read rows
	do
		sed -i -e '$a\'"${rows}" report.out	
	done 
	rm -f tmp_report.out
done
