# Minimax Usage Skill

Check your Minimax Coding Plan usage directly from Claude Code CLI.

## Quick Start (New Users)

1. **Get your credentials**:
   - API Key: https://platform.minimax.io/user-center/payment/coding-plan
   - Group ID: Found in the URL after selecting your group

2. **Configure** (add to ~/.zshrc or ~/.bashrc):
   ```bash
   export MINIMAX_CODING_API_KEY="sk-cp-..."
   export MINIMAX_GROUP_ID="your_group_id"
   ```

3. **Reload shell**: `source ~/.zshrc`

4. **Use in Claude Code**:
   ```
   /minimax-usage
   ```

## Usage

```
/minimax-usage
```

## Output

Shows:
- Total prompts in your plan
- Used prompts this billing cycle
- Remaining prompts
- Usage percentage
- Days remaining in billing cycle
- Pace indicator (are you over/under budget)
