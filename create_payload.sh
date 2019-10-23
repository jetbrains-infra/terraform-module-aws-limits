#!/bin/bash

cd code
rm lambda.zip
cd .tox/py37/lib/python3.7/site-packages/
py3clean
zip -r9 ${OLDPWD}/lambda.zip .
cd ${OLDPWD}
zip -g lambda.zip lambda.py config.yaml
