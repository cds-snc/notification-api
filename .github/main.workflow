workflow "Continuous Integration" {
  on = "push"
  resolves = ["docker://cdssnc/seekret-github-action"]
}

action "docker://cdssnc/seekret-github-action" {
  uses = "docker://cdssnc/seekret-github-action"
}
