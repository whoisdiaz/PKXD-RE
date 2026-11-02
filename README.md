# PK XD — engenharia reversa

## Etapa 1: lobby local para 1.38.4

O primeiro módulo aceita o protocolo `0.2.49` na rota real
`POST /lobby/allocation` e devolve uma alocação local. Funciona com Python e
biblioteca padrão, sem dependências de pip.

No Termux, na raiz deste projeto:

```sh
pkg install python curl
python -m pkxd_server --port 8080 --game-port 7000
```

Em outra sessão:

```sh
curl -sS http://127.0.0.1:8080/health
curl -sS http://127.0.0.1:8080/lobby/allocation \
  -H 'Content-Type: application/json' \
  --data '{"userToken":"local-test","gameServerProtocolVersion":"0.2.49","isPrivate":false}'
```

O módulo abre somente o lobby HTTP. A porta de jogo anunciada (`7000` no
exemplo), as sessões e a entrada no mundo pertencem às próximas partes. A
integração no APK 1.38.4 ainda não foi testada; o APK original não passa a usar
o servidor local automaticamente. O pedido do cliente leva o protocolo, não a
versão do aplicativo.

[Contrato reconstruído, redirecionamento de metadata e limites da etapa](docs/version_1_38_4.md).

Testes: `python -m unittest discover -s tests -v`.

## Dump e estudo inicial

[Baixar o dump IL2CPP (ZIP, 24,7 MiB)](https://github.com/whoisdiaz/PKXD-RE/raw/refs/heads/main/pkxd-dump.zip)

Dump gerado com Il2CppDumper v6.7.46 a partir de `global-metadata.dat` v29 e
`libil2cpp.so` Android ARM64 fornecidos para análise. A versão
foi identificada pelo usuário como dezembro de 2023; não foi confirmada por APK.

## Conteúdo

- `dump.cs`: 21.887 tipos e 146.636 métodos, com assinaturas, constantes e endereços disponíveis.
- 120 Dummy DLLs e uma DLL auxiliar; arquivos e scripts para Ghidra/IDA.
- Índices de 896 mensagens Protobuf e 147 enums.
- Estudos iniciais de autenticação, lobby, transporte e mensagens.
- Relatórios de validação, hashes e instruções de consulta no Termux.

O dump representa estruturas e assinaturas. Os corpos vazios dos métodos não
são implementações C# recuperadas; a lógica compilada continua no binário nativo.
O mapeamento nativo cobre 23.273 dos 23.281 literais de metadados; os oito
restantes estão documentados e os textos completos estão incluídos no pacote.

## No Termux

Baixe o ZIP pelo link acima e, na pasta em que ele foi salvo, execute:

```sh
pkg install unzip ripgrep
sha256sum -c pkxd-dump.zip.sha256
unzip pkxd-dump.zip
cd pkxd-dump
rg -n 'class LoginRequest|class LoginResponse' dump.cs
```

Para conferir o checksum, baixe também
[`pkxd-dump.zip.sha256`](pkxd-dump.zip.sha256) na mesma pasta do ZIP.

As demais partes do servidor serão implementadas conforme solicitadas pelo usuário.
