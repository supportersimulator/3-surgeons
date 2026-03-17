---
name: setup-api-keys
description: Interactive API key resolution — guides users through fixing missing surgeon API keys with detected options
---

# Setup API Keys

## When This Fires

- `probe` returns a surgeon with `status: "fail"` and a `remediation` field
- Any tool returns an auth error mid-operation
- User asks about API key configuration

## Flow

1. **Read the remediation plan** from the probe/tool response
2. **Present options** as a numbered list — only show sources where `available: true`
3. **Wait for user choice**
4. **Execute the resolution** based on choice
5. **Persist if requested** — offer Keychain storage for future sessions
6. **Re-run probe** to verify the fix worked

## Presenting Options

Format the `remediation.sources` into a clear menu:

```
🔑 {surgeon} needs {key_name} ({provider}).

{N}. {source.description}
   → `{source.resolve_command}`
{N+1}. Switch to a local model (free, no API key needed)
   → Available: {local_alternatives list}
{N+2}. Paste a key manually
   → I'll store it securely (env var or Keychain)
{N+3}. Skip for now
   → {skip_option}
```

Only show options where the tool is actually available. Don't show AWS if `aws` CLI isn't installed.

## Executing Each Choice

### Shell Profile (method: "shell_profile")
If `uses_command: true` (e.g., aws secretsmanager call in .zshrc):
```bash
# Run the export line to load the key
eval '{resolve_command}'
```
Then verify with probe.

If `uses_command: false` (plain value):
The key was likely auto-resolved by `diagnose_auth`. Just re-probe.

### AWS Secrets Manager (method: "aws_secretsmanager")
```bash
# Get the key value
KEY_VALUE=$(aws secretsmanager get-secret-value --secret-id {metadata.secret_id} --query SecretString --output text)
export {key_name}="$KEY_VALUE"
```
Then offer: "Want me to add this to your shell profile for future sessions?"

### 1Password (method: "1password")
```bash
KEY_VALUE=$(op item get "{provider}" --fields credential)
export {key_name}="$KEY_VALUE"
```

### macOS Keychain (method: "keychain")
If `metadata.exists: true`:
```bash
KEY_VALUE=$(security find-generic-password -s {metadata.service} -w)
export {key_name}="$KEY_VALUE"
```
If `metadata.exists: false`: Ask user for the key value, then store:
```bash
security add-generic-password -s {metadata.service} -a 3surgeons -w "{key_value}"
```

### Switch Provider (local alternative)
Edit `~/.3surgeons/config.yaml` to point the surgeon at the local backend:
```yaml
surgeons:
  cardiologist:
    provider: {detected.provider}
    endpoint: {detected.endpoint}
    model: {detected.models[0]}
```

### Manual Paste
**NEVER ask the user to paste a key in chat.** Instead:
```bash
# Guide them to set it in their environment
export {key_name}="your-key-here"
# Or store in Keychain
security add-generic-password -s 3surgeons-{surgeon} -a 3surgeons -w "your-key-here"
```

## After Resolution

1. Re-run `probe` to verify
2. If still failing, present remaining options
3. If all options exhausted, explain degraded mode (2/3 surgeons)

## Security Rules

- NEVER display or log the actual API key value
- If user accidentally pastes a key in chat, warn them to rotate it immediately
- Prefer Keychain/1Password over shell profile for persistence (encrypted at rest)
- All subprocess commands use 10s timeout
