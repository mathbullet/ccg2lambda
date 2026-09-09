#!/bin/bash
set -eu

raw_dir=data/raw
interim_dir=data/interim
mkdir -p ${raw_dir} ${interim_dir}

# Download SICK dataset (SemEval version)
cd ${raw_dir}
wget http://alt.qcri.org/semeval2014/task1/data/uploads/sick_test_annotated.zip
wget http://alt.qcri.org/semeval2014/task1/data/uploads/sick_train.zip
wget http://alt.qcri.org/semeval2014/task1/data/uploads/sick_trial.zip

unzip -o '*.zip'
mv SICK_test_annotated.txt SICK_test.txt

head -n 1 SICK_train.txt | awk '{print $0"\tSemEval_set"}' > SICK.semeval.txt
for dsplit in {train,trial,test}; do
  tail -n +2 SICK_${dsplit}.txt | awk -v dsplit=${dsplit} '{print $0"\t"toupper(dsplit);}'
done | sort -g -k1,1 >> SICK.semeval.txt

cd - > /dev/null

# Download VerbOcean
wget http://www.patrickpantel.com/download/data/verbocean/verbocean.unrefined.2004-05-20.txt.gz -P ${raw_dir}/
python en/verbocean_to_json.py ${raw_dir}/verbocean.unrefined.2004-05-20.txt.gz ${interim_dir}/verbocean.json
