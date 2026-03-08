param(
    [string]$ComfyUrl = "http://127.0.0.1:8000/",
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8765,
    [string]$ComfyInputDir = "C:\ComfyUI\input",
    [string]$OutputRoot = "C:\ComfyUI\output"
)

& python -B .\ltx23_web_ui.py --host $BindHost --port $Port --comfy-url $ComfyUrl --comfy-input-dir $ComfyInputDir --output-root $OutputRoot
