# Authoring and testing skills

Skillporter can help you write a skill, check it, see what each harness would receive, and test whether its description would trigger on the right requests.

## Create a skill

```bash
skillporter new release-notes --description "Draft release notes from merged pull requests. Use when asked for a changelog." --with-scripts --with-tests
```

This creates `release-notes/SKILL.md` with valid frontmatter and a structured body. The optional flags add a starter script, a references file and a `skill.test.yaml`. The name must be lowercase letters, digits and hyphens. An existing directory is left alone unless you pass `--force`.

## Lint

```bash
skillporter lint ./release-notes
skillporter lint ./release-notes --strict --harness cursor
```

`lint` reports problems with actionable messages: missing or malformed frontmatter, names that do not match the directory, weak descriptions with no trigger guidance, broken links and missing referenced files, scripts that nothing references, capability declarations that do not match what the scripts do, and security findings. Without `--strict`, warnings are reported but the exit code stays `0`. With `--strict`, any warning exits `1`. With `--harness`, it also checks limits that matter to that harness.

## Preview what a harness receives

```bash
skillporter preview ./release-notes --harness cursor
skillporter preview release-notes --harness claude-code --scope project
```

`preview` shows the target path and the content a harness would read. For harnesses that consume `SKILL.md` directly, that is the file itself. For harnesses that need a converted rules file, it shows the converted content and lists any information lost in the conversion. Nothing is written.

## Test activation

```yaml
# skill.test.yaml
should_trigger:
  - draft release notes for the last sprint
  - write a changelog from these pull requests
should_not:
  - fix this CSS
  - write a Python function
```

```bash
skillporter test ./release-notes
```

With no model configured, `test` runs a deterministic lexical check of your prompts against the skill name and description. It is reported as `deterministic_lexical`. It catches descriptions that share no terms with the prompts that should trigger them, and prompts that should not trigger but overlap heavily. It does not predict what a language model will do.

To compare against a real model, pass `--model provider:model` together with `--yes-send`. The descriptions and prompts are sent to that provider using your own API key from the environment. Nothing is sent without `--yes-send`.

## Limits

A passing test file shows that your examples behave as expected. It is not evidence that the skill activates correctly across real conversations.

See the [CLI reference](../commands/README.md) for every option.
