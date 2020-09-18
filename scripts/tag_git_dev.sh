#!/bin/bash
set -e

increase_patch_number () {
  first_portion=`echo $1 | cut -f1-2 -d'.'`
  patch_version=`echo $1 | cut -f3 -d'.'`

  if [[ $patch_version =~ [a-zA-Z] ]];then
    echo "Invalid patch format: $patch_version"
    exit 1
  else
    ((patch_version++))
    result="$first_portion.$patch_version"
  fi
  echo $result
}

get_latest_version_tag () {
  local latest_version_tag=$(git describe --tags --match="staging-v*")
  latest_version_tag=`echo $latest_version_tag | cut -f1-2 -d'-'`
  if [ -z "$latest_version_tag" ]; then
    latest_version_tag="staging-v0.0.0"
  fi
  echo $latest_version_tag
}

create_git_tag () {
  git tag $1 $2
  git push origin $1
}

current_version_tag=$(get_latest_version_tag)
incremented_tag=$(increase_patch_number $current_version_tag)
echo "::set-output name=TAG::$incremented_tag"
create_git_tag "$incremented_tag" "$1"