# Contributing to hub

Thanks for your interest! hub is young, so reports about how the method works (or doesn't) in
your team are as useful as code.

## Issues

GitHub issues are welcome: bugs in the scripts or the plugin, a command that does the wrong thing
with your forge (GitHub, GitLab, self-hosted), gaps in the template, ideas for the method. Please
leave out names of real companies, people and private repositories: describe the setup with
made-up names, like the Acme Books example.

## Running and testing

You need `git`, `python3` (3.8+), `bats`, `shellcheck` and `jq`. Claude Code is only needed to
validate the plugin.

```sh
python3 -m unittest discover -s tests     # hub.py, dora.py, radar-md.py
bats tests/                               # merge-seq.sh against fake gh/glab, check-leaks.sh, the CLI
shellcheck bin/hub scripts/*.sh plugin/scripts/*.sh tests/fakes/*
claude plugin validate plugin && claude plugin validate .
```

To try the plugin from your checkout: `claude --plugin-dir ./plugin`.

CI runs the tests, shellcheck, a JSON parse of the manifests, gitleaks and the term scan on every
push and pull request.

## Style and rules

- Python uses the standard library only and must run on 3.8+. Shell scripts are bash and pass
  `shellcheck`.
- New behaviour in the scripts comes with a test. Anything that talks to `gh` or `glab` is tested
  against the fakes in `tests/fakes/`, never against a real forge.
- Commands and the template keep the method's rules: absolute dates, drafts before merges, merges
  and force pushes never automatic, metrics per repo and never per person.
- Code, comments and docs in English; the template's Spanish headings (`--lang es`) are kept in
  sync with the English ones.
- Examples and fixtures use made-up names only. `scripts/check-leaks.sh` scans for terms that
  must never be published (the list lives outside the repository).

## License

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE).
