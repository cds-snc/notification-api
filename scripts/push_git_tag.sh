#!/bin/bash
set -e

create_git_tag () {
  version=`echo $1 | cut -f2 -d'-' | tr -d 'v'`
  git tag $version
  git push origin $version
}

create_git_tag "$1"