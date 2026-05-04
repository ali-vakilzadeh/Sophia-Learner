'=====================================================================
' Export Excel Hireachical Range to JSON (with outline hierarchy)
' 
' Description:
'   Exports selected range of rows & columns into hierarchical JSON
'   based on Excel OutlineLevel.
'
' Features:
'   - Asks user for scope (start/end rows and columns)
'   - Max 16 columns (extra columns ignored with warning) - see line 28
'   - Optional first row as headers
'   - Stores row number & outlineLevel
'   - Children (nested levels) stored under "childLevels":[]
'   - Supports outline level hopping (e.g. level 1 to level 4 forward and backward)
'   - 2-space indentation (you can change line 87) , commas at same line ends
'=====================================================================

Option Explicit

Sub ExportExcelToJSON()
  Dim ws As Worksheet
  Dim startRow As Long, endRow As Long, startColLetter As String, endColLetter As String
  Dim startCol As Long, endCol As Long, useHeaders As VbMsgBoxResult
  Dim filePath As String, jsonText As String, maxCols As Integer
  Dim headers() As String, i As Long, j As Long
  Dim numCols As Long
  
  maxCols = 16
  Set ws = ActiveSheet
  
  '--- Ask user for range ---
  startRow = CLng(InputBox("Enter start row:", "Export Scope"))
  endRow = CLng(InputBox("Enter end row:", "Export Scope"))
  startColLetter = InputBox("Enter the starting column letter (e.g., A, AA):", "Start Column")
  If startColLetter = "" Then Exit Sub                                                                                                                  ' User cancelled
    startCol = ColumnLetterToNumber(startColLetter)
  endColLetter = InputBox("Enter the ending column letter (e.g., Z, AN):", "End Column")
  If endColLetter = "" Then Exit Sub                                                                                                                    ' User cancelled
    endCol = ColumnLetterToNumber(endColLetter)
  useHeaders = MsgBox("Use first row as headers?", vbYesNo, "Headers")

  If startRow = 0 Or endRow = 0 Or startColLetter = "" Or endColLetter = "" Then
    MsgBox "Invalid inputs, exiting.", vbCritical
    Exit Sub
  End If

  numCols = endCol - startCol + 1
  If numCols > maxCols Then
    MsgBox "Warning: More than 16 columns selected. Only first 16 will be exported.", vbExclamation
    numCols = maxCols
    endCol = startCol + maxCols - 1
  End If

  '--- Ask for save file path ---
  filePath = Application.GetSaveAsFilename( _
      InitialFileName:="Export.json", _
      FileFilter:="JSON Files (*.json), *.json", _
      Title:="Select File Location to Save Exported JSON")
  If filePath = "False" Then Exit Sub
  
  '--- Read headers ---
  ReDim headers(1 To numCols)
  If useHeaders = vbYes Then
    For i = 1 To numCols
      headers(i) = CleanJSON(Trim(ws.Cells(startRow, startCol + i - 1).Value))
      If headers(i) = "" Then headers(i) = "Column" & i
    Next i
    startRow = startRow + 1
  Else
    For i = 1 To numCols
      headers(i) = "Column" & i
    Next i
  End If

  '--- Build JSON ---
  jsonText = "{""headers"": ["
  For i = 1 To numCols
    jsonText = jsonText & """" & headers(i) & """"
    If i < numCols Then jsonText = jsonText & ", "
  Next i
  jsonText = jsonText & "]," & vbCrLf & """rows"": [" & vbCrLf

  '--- Process hierarchy using stack ---
  Dim rowsData As Collection
  Set rowsData = CollectRows(ws, startRow, endRow, startCol, endCol, headers)

  jsonText = jsonText & SerializeRows(rowsData, 2)
  jsonText = jsonText & "]}" & vbCrLf

  '--- Write to file ---
  WriteTextFile filePath, jsonText
  MsgBox "Export completed successfully at: " & filePath, vbInformation
  
End Sub

'=====================================================================
' Collect all rows with hierarchy
'=====================================================================
Function CollectRows(ws As Worksheet, sRow As Long, eRow As Long, sCol As Long, eCol As Long, headers() As String) As Collection
  Dim root As New Collection
  Dim stack As New Collection ' keeps hierarchy track
  Dim i As Long, j As Long, lvl As Long
  Dim currentItem As Object
  Dim parent As Object
  
  For i = sRow To eRow
    Dim rowObj As Object
    Set rowObj = CreateObject("Scripting.Dictionary")
    rowObj("row") = i
    rowObj("outlineLevel") = ws.rows(i).outlineLevel

    For j = 1 To UBound(headers)
      rowObj(headers(j)) = CleanJSON(CStr(ws.Cells(i, sCol + j - 1).Value))
    Next j
    Set rowObj("childLevels") = New Collection

    lvl = ws.rows(i).outlineLevel
    
    '-- Adjust stack for hops --
    Do While stack.Count > 0
      If stack(stack.Count)("outlineLevel") >= lvl Then
       stack.Remove stack.Count
      Else
        Exit Do
      End If
    Loop

    If stack.Count = 0 Then
      root.Add rowObj
    Else
      Set parent = stack(stack.Count)
      parent("childLevels").Add rowObj
    End If
    
    stack.Add rowObj
  Next i

  Set CollectRows = root
End Function

'=====================================================================
' Serialize Collection hierarchy to JSON text
'=====================================================================
Function SerializeRows(rows As Collection, indent As Integer) As String
  Dim i As Long, json As String, r As Object
  Dim spaces As String
  spaces = String(indent, " ")
  
  For i = 1 To rows.Count
    Set r = rows(i)
    json = json & spaces & "{" & vbCrLf
    json = json & spaces & "  ""row"": " & r("row") & "," & vbCrLf
    json = json & spaces & "  ""outlineLevel"": " & r("outlineLevel") & "," & vbCrLf
    
    Dim key As Variant
    For Each key In r.Keys
      If key <> "row" And key <> "outlineLevel" And key <> "childLevels" Then
        json = json & spaces & "  """ & key & """: """ & Replace(r(key), """", "'") & """," & vbCrLf
      End If
    Next key
    
    json = json & spaces & "  ""childLevels"": [" & vbCrLf
    json = json & SerializeRows(r("childLevels"), indent + 2)
    json = json & spaces & "  ]" & vbCrLf
    json = json & spaces & "}," & vbCrLf
  Next i

  SerializeRows = json
End Function

'=====================================================================
' Write text to file
'=====================================================================
Sub WriteTextFile(path As String, text As String)
    Dim stream As Object
    Set stream = CreateObject("ADODB.Stream")
    
    stream.Type = 2 ' adTypeText
    stream.Charset = "utf-8"
    stream.Open
    stream.WriteText text
    stream.SaveToFile path, 2 ' adSaveCreateOverWrite
    stream.Close
End Sub

'=====================================================================
' Sanitize the cell contents - remove JSON incompatible characters
'=====================================================================
Function CleanJSON(ByVal str As String) As String
    ' Replace double quotes with escaped double quotes
    str = Replace(str, """", "\""")
    ' Remove line breaks (CR and LF) and tabs
    str = Replace(str, vbCr, " ")
    str = Replace(str, vbLf, " ")
    str = Replace(str, vbTab, " ")
    ' You can add more cleanup if needed
    CleanJSON = str
End Function

'=====================================================================
' Convert column letters to numbers
'=====================================================================
Function ColumnLetterToNumber(colLetter As String) As Long
    Dim i As Integer
    Dim num As Long
    Dim multiplier As Long
    Dim charCode As Integer

    num = 0
    multiplier = 1
    colLetter = UCase(colLetter) ' Ensure input is uppercase for consistent processing

    ' Loop from the rightmost character to the leftmost
    For i = Len(colLetter) To 1 Step -1
        charCode = Asc(Mid(colLetter, i))

        ' Check if it's a valid letter A-Z
        If charCode >= 65 And charCode <= 90 Then ' ASCII codes for A-Z
            num = num + (charCode - 64) * multiplier
            multiplier = multiplier * 26
        Else
            ' Handle invalid characters if necessary, or just ignore them
            ' For this fix, we'll assume valid input or let it result in an incorrect number
            ' A more robust solution might include error handling here.
            ' For now, let's just stop processing if an invalid char is found
            MsgBox "Invalid character '" & Mid(colLetter, i) & "' found in column letter.", vbExclamation
            ColumnLetterToNumber = -1 ' Indicate an error
            Exit Function
        End If
    Next i

    ColumnLetterToNumber = num
End Function

