# Baixador de Vídeos do Youtube

Este projeto é uma aplicação em Python (CLI) que permite baixar vídeos do YouTube com total controle e autonomia.

Utilizando a biblioteca yt-dlp, o programa consulta e exibe detalhadamente todos os formatos de vídeo e áudio disponíveis para cada link fornecido. O usuário pode visualizar as informações técnicas como resolução, bitrate, codec e outros parâmetros.

Após a análise das informações, o sistema solicita ao usuário que informe os IDs desejados para vídeo e áudio. Em seguida, basta confirmar para que o download seja iniciado.

## Requisitos

- [Python 3.13.7](https://www.python.org/downloads/)  (Recomendado)
- [Node.js](https://nodejs.org/en/download) instalado e acessível via PATH
    - Utilizado como ambiente para execução de scripts JavaScript pelo yt-dlp
- [FFmpeg](https://ffmpeg.org/download.html) instalado e acessível via PATH
    - Utilizado para realizar o merge e o remux dos arquivos de vídeo e áudio

## Como Usar

### **Baixe o zip ou clone o repositório**

1. Instale as dependências:

   ```
   python -m pip install -r requirements.txt
   ```

2. Execute o programa:

   ```
   python main.py
   ```

Siga as instruções no terminal.
