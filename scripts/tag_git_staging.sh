#!/bin/bash
set -e

create_git_tag () {
  removed_refs=`echo $1 | cut -f3 -d'/'`
  version=`echo $removed_refs | cut -f2 -d'-'`
  git tag $version
  git push origin $version
}

create_git_tag "$1"

echo "STAGING_TAG=$removed_refs" >> $GITHUB_OUTPUT
echo "TAG=$version" >> $GITHUB_OUTPUT