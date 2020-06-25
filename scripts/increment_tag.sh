#!/bin/bash

increase_patch_number () {
  patch_version=`echo $1 | sed 's/\(.*[0-9]\.\)\([0-9]\)/\2/'`
  first_portion=`echo $1 | sed 's/\(.*[0-9]\.\)\([0-9]\)/\1/'`

  if [[ $patch_version =~ [a-zA-Z] ]];then
    echo "Invalid patch format: $patch_version"
    exit 1
  else
    ((patch_version++))
    result=$first_portion$patch_version
  fi
  echo $result
}

get_latest_version_tag () {
  local latest_version_tag=$(git describe --tags `git rev-list --tags --max-count=1`)
  if [ -z "$latest_version_tag" ]; then
    latest_version_tag="rc-0.0.0"
  fi
  echo $latest_version_tag
}

create_git_tag () {
  echo "git tag $1 $2"
  echo "git push origin $1"
}

current_version_tag=$(get_latest_version_tag)
incremented_tag=$(increase_patch_number $current_version_tag)
create_git_tag "$incremented_tag" "$1"