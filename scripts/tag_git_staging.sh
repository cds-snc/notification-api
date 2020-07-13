#!/bin/bash
set -e

create_git_tag () {
  removed_refs=`echo $1 | cut -f3 -d'/'`
  version=`echo $removed_refs | cut -f2 -d'-'`
  git tag $version
  git push origin $version
}

create_git_tag "$1"

echo "::set-env name=STAGING_TAG::$removed_refs"
echo "::set-env name=TAG::$version"