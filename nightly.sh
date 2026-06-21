#!/bin/bash

bash -c "source ~mslaney/miniconda3/etc/profile.d/conda.sh; conda init bash; conda activate quicksin; cd /var/www/jnd; python3 offline_asr.py"

new_filename=$(date "+%Y-%m-%d")_experiments.db
# cp experiments.db ~/StanfordAudiologyDrive/QuickSIN/backup/$new_filename
cp experiments.db ~/StanfordAudiologyDrive/QuickSINShortcut/backup/$new_filename
