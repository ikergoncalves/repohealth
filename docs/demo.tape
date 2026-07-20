# VHS tape for docs/demo.gif — https://github.com/charmbracelet/vhs
# Run from the repository root: vhs docs/demo.tape

Output docs/demo.gif

Set FontSize 16
Set Width 1200
Set Height 700
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms

Type "repohealth scan ."
Enter
Sleep 3s

Type "repohealth report ."
Enter
Sleep 4s

Type "repohealth hotspots . --top 5"
Enter
Sleep 4s
