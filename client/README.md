# Metadata para o teste local da 1.38.4

[Baixar o pacote](pkxd-1.38.4-metadata-local.zip) — cerca de 4,6 MiB.
Na página do ZIP no GitHub, use **Download raw file**.

O arquivo `global-metadata.dat` dentro do ZIP aponta os dois hosts de lobby
de produção para `http://127.0.0.1:8080`. O metadata original é preservado.
O protocolo continua sendo `0.2.49`.

1. Inicie `python server.py` no Termux.
2. Extraia `global-metadata.dat` do pacote.
3. Substitua a entrada `global-metadata.dat` no APK correspondente, mantendo o
   nome e o caminho que já existem nele. Salve/empacote e assine a alteração
   com a ferramenta de APK que você utiliza.
4. Abra o jogo no mesmo aparelho. O console do servidor deve mostrar
   `POST /lobby/allocation status=200` quando o cliente alcançar essa etapa.

Um arquivo alterado fora do APK não muda o cliente instalado. O pacote não
redireciona as contas/Firebase e não contém a implementação de autenticação,
transporte ou mundo. A conexão real no Android continua pendente de teste.

O pacote foi gerado somente para o metadata enviado neste projeto. Seus hashes
e os dois índices modificados estão em [manifest.json](manifest.json).
O checksum do arquivo ZIP está em
[pkxd-1.38.4-metadata-local.zip.sha256](pkxd-1.38.4-metadata-local.zip.sha256).
Os arquivos internos têm seu próprio `SHA256SUMS`.

Para gerar novamente o metadata a partir do original, use
[`tools/redirect_lobby_metadata.py`](../tools/redirect_lobby_metadata.py).
