# PK XD — engenharia reversa

## Etapa 1: lobby local para 1.38.4

O primeiro módulo permite o protocolo `0.2.49` na rota real
`POST /lobby/allocation` e devolve uma alocação local. A versão **1.38.4** já
vem habilitada em [`config/versions.json`](config/versions.json).
Funciona com Python e biblioteca padrão, sem dependências de pip.

Para instalar no Termux:

```sh
pkg install git python curl
git clone --depth 1 https://github.com/whoisdiaz/PKXD-RE.git
cd PKXD-RE
python server.py
```

Se já tiver o repositório, execute `git pull --ff-only` na pasta dele para
atualizar. O início por `python -m pkxd_server` também é suportado.

O servidor escuta em `127.0.0.1:8080`. Deixe essa sessão aberta.
Em outra sessão:

```sh
curl -sS http://127.0.0.1:8080/health
curl -sS http://127.0.0.1:8080/lobby/allocation \
  -H 'Content-Type: application/json' \
  --data '{"userToken":"local-test","gameServerProtocolVersion":"0.2.49","isPrivate":false}'
```

Para o cliente consultar esse lobby, use o
[metadata já redirecionado para teste local](client/README.md) no APK
correspondente. Não é necessário enviar o APK inteiro para essa primeira
tentativa. A configuração de rede será investigada se o teste apresentar
um bloqueio de HTTP.

Para desabilitar a versão, altere `enabled` para `false` em
`config/versions.json` e reinicie o servidor. A requisição nativa informa o
protocolo, então outras builds que compartilhem `0.2.49` não podem ser
distintas por esse pedido sozinho.

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
