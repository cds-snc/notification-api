git checkout main
git pull

# Delete all local branches already merged into main
git branch --merged main \
  | grep -v '^\*' \
  | grep -v '^main$' \
  | xargs -r git branch -d
