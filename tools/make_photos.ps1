# Генерує фото-заглушки 800x800 для товарів з products.csv у папку photos/.
# Магазин демо, тож замість справжніх фото - картки з назвою товару.
param([string]$Out = (Join-Path $PSScriptRoot '..\photos'))

Add-Type -AssemblyName System.Drawing
New-Item -ItemType Directory -Force $Out | Out-Null

$colors = @{
    'Кухня'    = @('#E07A5F', '#F2CC8F')
    'Текстиль' = @('#3D405B', '#81B29A')
    'Декор'    = @('#6D597A', '#E5989B')
}

$products = Import-Csv (Join-Path $PSScriptRoot '..\products.csv') -Delimiter ';' -Encoding UTF8
foreach ($p in $products) {
    $size = 800
    $bmp = New-Object System.Drawing.Bitmap $size, $size
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = 'AntiAlias'
    $g.TextRenderingHint = 'AntiAliasGridFit'

    $pair = $colors[$p.category]
    if (-not $pair) { $pair = @('#555555', '#999999') }
    $rect = New-Object System.Drawing.Rectangle 0, 0, $size, $size
    $grad = New-Object System.Drawing.Drawing2D.LinearGradientBrush $rect, ([System.Drawing.ColorTranslator]::FromHtml($pair[0])), ([System.Drawing.ColorTranslator]::FromHtml($pair[1])), 45
    $g.FillRectangle($grad, $rect)

    # біла картка в центрі
    $card = New-Object System.Drawing.Drawing2D.GraphicsPath
    $r = 40; $x = 80; $y = 160; $w = 640; $h = 480
    $card.AddArc($x, $y, $r, $r, 180, 90)
    $card.AddArc($x + $w - $r, $y, $r, $r, 270, 90)
    $card.AddArc($x + $w - $r, $y + $h - $r, $r, $r, 0, 90)
    $card.AddArc($x, $y + $h - $r, $r, $r, 90, 90)
    $card.CloseFigure()
    $g.FillPath((New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(235, 255, 255, 255))), $card)

    $fmt = New-Object System.Drawing.StringFormat
    $fmt.Alignment = 'Center'
    $fmt.LineAlignment = 'Center'
    $dark = New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml('#2B2D42'))
    $muted = New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml('#6C6F7F'))

    $g.DrawString($p.category.ToUpper(), (New-Object System.Drawing.Font 'Segoe UI', 20, ([System.Drawing.FontStyle]::Bold)), $muted, (New-Object System.Drawing.RectangleF $x, ($y + 30), $w, 50), $fmt)
    $g.DrawString($p.name, (New-Object System.Drawing.Font 'Segoe UI', 40, ([System.Drawing.FontStyle]::Bold)), $dark, (New-Object System.Drawing.RectangleF ($x + 40), ($y + 90), ($w - 80), 260), $fmt)
    $g.DrawString("$($p.price) грн", (New-Object System.Drawing.Font 'Segoe UI', 34), $dark, (New-Object System.Drawing.RectangleF $x, ($y + 360), $w, 80), $fmt)
    $g.DrawString('Домівка · демо', (New-Object System.Drawing.Font 'Segoe UI', 18), (New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::White)), (New-Object System.Drawing.RectangleF 0, 700, $size, 60), $fmt)

    $path = Join-Path $Out $p.photo
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Jpeg)
    $g.Dispose(); $bmp.Dispose()
    Write-Output "$path"
}
