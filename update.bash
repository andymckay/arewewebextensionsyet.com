git pull
pushd ../firefox/head-for-scripts/ && hg pull && hg update
popd
python generate.py
git commit -m "daily changes" -a
git push
