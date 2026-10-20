# Fills the AI Builder Cup template with deck/content.json through PowerPoint COM and writes
# deck/AI-Builder-Cup-Submission.pptx and .pdf. The template is opened read-only and never saved.
# Usage: powershell -ExecutionPolicy Bypass -File deck/build_deck.ps1 [-Png]
#   -Png  also exports every slide to deck/render/slide-NN.png for visual QA.
param([switch]$Png)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$content = Get-Content -Raw -Encoding UTF8 -Path (Join-Path $PSScriptRoot 'content.json') | ConvertFrom-Json

$templatePath = Join-Path $root $content.template
$outBase = Join-Path $root $content.output
$pptxPath = [System.IO.Path]::GetFullPath("$outBase.pptx")
$pdfPath = [System.IO.Path]::GetFullPath("$outBase.pdf")
if (-not (Test-Path -LiteralPath $templatePath)) { throw "Template not found: $templatePath" }

# Layout (points, 720 x 405 slide): the content area sits below the template's title box and above
# its bottom bar; the body and diagrams share the title box's left edge and width.
$areaLeft = 20.9
$areaTop = 97.0
$areaWidth = 678.2
$areaBottom = 395.0
$bodyFont = 'Google Sans Flex'
$bodySize = [single]16

function Test-FileLocked([string]$path) {
  if (-not (Test-Path -LiteralPath $path)) { return $false }
  try { $fs = [System.IO.File]::Open($path, 'Open', 'ReadWrite', 'None'); $fs.Close(); return $false }
  catch { return $true }
}

function Get-TitleShape($slide) {
  # The topmost shape with text holds the slide's title in its first paragraph.
  $best = $null
  foreach ($sh in $slide.Shapes) {
    if ($sh.HasTextFrame -and $sh.TextFrame.HasText -and $sh.TextFrame.TextRange.Text.Trim()) {
      if ($null -eq $best -or $sh.Top -lt $best.Top) { $best = $sh }
    }
  }
  return $best
}

function Get-SlideTitle($slide) {
  $sh = Get-TitleShape $slide
  if ($null -eq $sh) { return '' }
  return $sh.TextFrame.TextRange.Paragraphs(1).Text.Trim()
}

function Get-Format($range) {
  return @{
    Name = $range.Font.Name; Size = $range.Font.Size; Bold = $range.Font.Bold; Color = $range.Font.Color.RGB
    Bullet = $range.ParagraphFormat.Bullet.Visible; Indent = $range.IndentLevel
  }
}

function Set-Format($range, $fmt) {
  $range.Font.Name = $fmt.Name
  $range.Font.Size = $fmt.Size
  $range.Font.Bold = $fmt.Bold
  $range.Font.Color.RGB = $fmt.Color
  $range.IndentLevel = $fmt.Indent
  $range.ParagraphFormat.Bullet.Visible = $fmt.Bullet
  $range.ParagraphFormat.Alignment = 1
}

function Get-SlideById($pres, $id) {
  # Slides.FindBySlideID returns nothing through PowerShell's COM binder, so search by hand.
  foreach ($s in $pres.Slides) { if ($s.SlideID -eq $id) { return $s } }
  throw "No slide with ID $id"
}

function Set-Notes($slide, [string]$text) {
  if (-not $text) { return }
  foreach ($sh in $slide.NotesPage.Shapes) {
    if ($sh.Type -eq 14 -and $sh.PlaceholderFormat.Type -eq 2) { $sh.TextFrame.TextRange.Text = $text; return }
  }
  throw "Slide $($slide.SlideIndex) has no notes body placeholder"
}

function Fill-Slide($slide, $spec) {
  $titleShape = Get-TitleShape $slide
  if ($null -eq $titleShape) { throw "Slide $($slide.SlideIndex) has no title box" }
  $tr = $titleShape.TextFrame.TextRange
  $title = if ($spec.title) { $spec.title } else { $tr.Paragraphs(1).Text.Trim() }
  $titleFmt = Get-Format $tr.Paragraphs(1)
  $titleFmt.Bullet = 0

  if ($spec.inline) {
    # Body continues inside the title box (Team Details), in the box's own body format.
    $bodyFmt = $null
    for ($p = 2; $p -le $tr.Paragraphs().Count; $p++) {
      if ($tr.Paragraphs($p).Text.Trim()) { $bodyFmt = Get-Format $tr.Paragraphs($p); break }
    }
    if ($null -eq $bodyFmt) { throw "Slide $($slide.SlideIndex): inline body needs a body paragraph to copy" }
    $gapFmt = Get-Format $tr.Paragraphs(2)
    $lines = @($title, '') + @($spec.body)
    $tr.Text = ($lines -join "`r")
    Set-Format $tr.Paragraphs(1) $titleFmt
    Set-Format $tr.Paragraphs(2) $gapFmt
    for ($p = 3; $p -le $tr.Paragraphs().Count; $p++) { Set-Format $tr.Paragraphs($p) $bodyFmt }
  } else {
    $tr.Text = $title
    Set-Format $tr $titleFmt
  }

  # Other text boxes from the template (example text) give way to the content.
  $extra = @()
  foreach ($sh in $slide.Shapes) {
    if ($sh.Name -ne $titleShape.Name -or $sh.Top -ne $titleShape.Top) {
      if ($sh.Type -eq 17) { $extra += $sh }
    }
  }
  foreach ($sh in $extra) { $sh.Delete() }

  if ($spec.image -and $spec.body -and -not $spec.inline) { throw "Slide '$title': use image or body, not both" }

  if ($spec.image) {
    $img = Join-Path $root $spec.image
    if (-not (Test-Path -LiteralPath $img)) { throw "Image not found: $img" }
    $pic = $slide.Shapes.AddPicture($img, 0, -1, $areaLeft, $areaTop)
    $pic.LockAspectRatio = -1
    $scale = [math]::Min($areaWidth / $pic.Width, ($areaBottom - $areaTop) / $pic.Height)
    $pic.Width = $pic.Width * $scale
    $pic.Left = $areaLeft + ($areaWidth - $pic.Width) / 2
    $pic.Top = $areaTop
    $pic.Name = 'Content image'
  } elseif ($spec.body -and -not $spec.inline) {
    $box = $slide.Shapes.AddTextbox(1, $areaLeft, $areaTop, $areaWidth, $areaBottom - $areaTop)
    $box.Name = 'Content body'
    $tf = $box.TextFrame
    $tf.WordWrap = -1
    $tf.AutoSize = 0
    $tf.MarginLeft = 7.15; $tf.MarginRight = 7.15; $tf.MarginTop = 7.15; $tf.MarginBottom = 7.15
    $tf.TextRange.Text = (@($spec.body) -join "`r")
    $r = $tf.TextRange
    $r.Font.Name = $bodyFont
    $r.Font.Size = $bodySize
    $r.Font.Bold = 0
    $r.Font.Color.RGB = 0
    $r.ParagraphFormat.Alignment = 1
    $r.ParagraphFormat.SpaceAfter = 6
    $r.ParagraphFormat.Bullet.Visible = -1
    $r.ParagraphFormat.Bullet.Type = 1   # ppBulletUnnumbered
    $r.ParagraphFormat.Bullet.Character = 8226
    $box.TextFrame.Ruler.Levels(1).FirstMargin = 0
    $box.TextFrame.Ruler.Levels(1).LeftMargin = 16
  }

  Set-Notes $slide $spec.notes
}

if (Test-FileLocked $pptxPath) { throw "Output is open in another program (PowerPoint?): $pptxPath. Close it and run again." }
if (Test-FileLocked $pdfPath) { throw "Output is open in another program: $pdfPath. Close it and run again." }

$app = New-Object -ComObject PowerPoint.Application
foreach ($p in $app.Presentations) {
  if ($p.FullName -eq $pptxPath) { throw "PowerPoint has the output open: $pptxPath. Close it and run again." }
}
$pres = $null
$copyPath = $null
try {
  # ReadOnly, Untitled, no window: the template file itself is never written.
  $pres = $app.Presentations.Open($templatePath, -1, -1, 0)
  $last = $pres.Slides.Count

  # Classify the template's slides by title.
  $byTitle = @{}
  $origIndex = @{}
  $toDelete = @()
  for ($i = 1; $i -le $last; $i++) {
    $s = $pres.Slides($i)
    $t = Get-SlideTitle $s
    if ($i -eq $last -and -not $t) { continue }   # Thank you: picture only, kept as is
    if (-not $t) { $toDelete += $s.SlideID; continue }   # blank frame slide
    $drop = $false
    foreach ($prefix in $content.remove_title_prefixes) { if ($t.StartsWith($prefix)) { $drop = $true } }
    if ($drop) { $toDelete += $s.SlideID; continue }
    if ($byTitle.ContainsKey($t)) { throw "Two template slides share the title '$t'" }
    $byTitle[$t] = $s.SlideID
    $origIndex[$t] = $i
  }

  # Match every content entry to exactly one template slide, and every template slide to an entry.
  $plan = @()
  $used = @{}
  foreach ($spec in $content.slides) {
    $hits = @($byTitle.Keys | Where-Object { $_.StartsWith($spec.match) })
    if ($hits.Count -ne 1) { throw "content.json match '$($spec.match)' hits $($hits.Count) template slides" }
    if ($used[$hits[0]]) { throw "Two content.json entries match template slide '$($hits[0])'" }
    $used[$hits[0]] = $true
    $plan += , @($byTitle[$hits[0]], $spec, $origIndex[$hits[0]])
  }
  foreach ($t in $byTitle.Keys) { if (-not $used[$t]) { throw "Template slide '$t' has no entry in content.json" } }

  # Added slides: copies of their anchor slide (header bar, brand images), made before filling.
  # Slide.Duplicate() is a silent no-op under WPS Office's PowerPoint COM, so each copy is inserted
  # from a temporary copy of the template (InsertFromFile fails on the file that is open).
  $addedPlan = @()
  foreach ($item in $plan) {
    $spec = $item[1]
    if (-not $spec.added) { continue }
    if (-not $copyPath) {
      $copyPath = Join-Path ([System.IO.Path]::GetTempPath()) ("dss-deck-template-{0}.pptx" -f [guid]::NewGuid())
      Copy-Item -LiteralPath $templatePath -Destination $copyPath
    }
    $anchor = Get-SlideById $pres $item[0]
    $srcIndex = $item[2]   # the anchor's index in the unchanged template copy
    $pos = $anchor.SlideIndex
    foreach ($a in $spec.added) {
      $before = $pres.Slides.Count
      $null = $pres.Slides.InsertFromFile($copyPath, $pos, $srcIndex, $srcIndex)
      if ($pres.Slides.Count -ne $before + 1) { throw "Could not copy slide $srcIndex for '$($a.title)'" }
      $pos++
      $addedPlan += , @($pres.Slides($pos).SlideID, $a)
    }
  }

  foreach ($item in ($plan + $addedPlan)) {
    $s = Get-SlideById $pres $item[0]
    if ($item[1].remove) { $toDelete += $item[0]; continue }
    Fill-Slide $s $item[1]
  }
  if ($content.closing_notes) { Set-Notes $pres.Slides($pres.Slides.Count) $content.closing_notes }
  foreach ($id in $toDelete) { (Get-SlideById $pres $id).Delete() }

  if (Test-Path -LiteralPath $pptxPath) { Remove-Item -LiteralPath $pptxPath }
  if (Test-Path -LiteralPath $pdfPath) { Remove-Item -LiteralPath $pdfPath }
  $pres.SaveAs($pptxPath, 24)   # ppSaveAsOpenXMLPresentation
  $pres.SaveAs($pdfPath, 32)    # ppSaveAsPDF
  Write-Output "wrote $pptxPath ($($pres.Slides.Count) slides)"
  Write-Output "wrote $pdfPath"

  if ($Png) {
    $renderDir = Join-Path $PSScriptRoot 'render'
    New-Item -ItemType Directory -Force -Path $renderDir | Out-Null
    Get-ChildItem -LiteralPath $renderDir -Filter 'slide-*.png' | Remove-Item
    foreach ($s in $pres.Slides) {
      $s.Export((Join-Path $renderDir ('slide-{0:D2}.png' -f $s.SlideIndex)), 'PNG', 1920, 1080)
    }
    Write-Output "exported $($pres.Slides.Count) PNGs to $renderDir"
  }
} finally {
  # Each cleanup step runs even if an earlier one fails.
  # A modified presentation closed without Saved waits on a hidden "save changes?" prompt (WPS).
  try { if ($null -ne $pres) { $pres.Saved = -1; $pres.Close() } } catch { Write-Warning "Close failed: $_" }
  try { if ($app.Presentations.Count -eq 0) { $app.Quit() } } catch { Write-Warning "Quit failed: $_" }
  try { if ($copyPath -and (Test-Path -LiteralPath $copyPath)) { Remove-Item -LiteralPath $copyPath } } catch { Write-Warning "Temp copy not removed: $copyPath" }
  try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null } catch {}
}
