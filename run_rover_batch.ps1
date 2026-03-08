param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RunnerArgs
)

& python -B .\ltx23_batch_runner.py @RunnerArgs
