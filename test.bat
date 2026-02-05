@echo off
curl -X POST http://localhost:18081/v1/log ^
  -H "Content-Type: application/json" ^
  -d "{""level"":""info"",""message"":""Build ready for review""}"
