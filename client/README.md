# Metadata de contas + lobby para 1.38.4

[Baixar o novo pacote](pkxd-1.38.4-account-local.zip) — cerca de 4,6 MiB.
Na página do ZIP no GitHub, use **Download raw file**.

O `global-metadata.dat` do pacote aponta três literais para `http://127.0.0.1:8080`:
o serviço de contas Faster e os dois hosts de lobby. Foi gerado a partir do
metadata original enviado; preserva o tamanho, os demais literais e o protocolo `0.2.49`.

1. Pare o servidor antigo com Ctrl+C, atualize o repositório e inicie `python server.py`.
2. Extraia `global-metadata.dat` deste **novo pacote**.
3. Substitua a entrada `global-metadata.dat` no APK correspondente, mantendo o
   nome e o caminho que já existem nele. Salve/empacote e assine a alteração
   com a ferramenta de APK que você utiliza.
4. Abra o jogo no mesmo aparelho e toque em **Novo jogador**.

O console deve registrar o progresso à medida que o cliente alcançar cada etapa:

```text
POST /v1/identity/anonymous/sign-up status=200
POST /v1/auth/sessions status=200
POST /v1/users/sessions status=200
POST /lobby/allocation status=200
TCP connected; waiting for game login
TCP login accepted; newCharacter=true
TCP character bootstrap sent
```

Ao receber as ações correspondentes, registra `TCP character appearance saved (equip)`
e `TCP character name saved`. A ordem pode incluir renovação e outras chamadas.

Atualizar só o Python ou deixar o metadata extraído na pasta do celular não
altera o APK instalado. O pacote anterior alterava apenas o lobby. Tokens e
contas oficiais não são importados: um token oficial armazenado será recusado
pelas contas locais. Não apague os dados do aplicativo para tentar contornar
isso; primeiro confira o erro e se **Novo jogador** cria a identidade local.

Se continuar sem chamadas, confira o APK instalado, o metadata e eventual erro
de rede no Android. Se avançar, a última linha e eventos `unsupported` indicam
o próximo contrato necessário. Não é preciso enviar o APK inteiro de antemão.

O pacote não altera certificados, assinaturas, Firebase ou URLs de assets.
A tela real e a disponibilidade dos assets de 2023 precisam de teste no aparelho.
O mundo jogável é outra etapa. Veja [contratos e limites](../docs/character_1_38_4.md).

O pacote foi gerado somente para o metadata enviado neste projeto. Seus hashes
e os três índices modificados estão em [account-manifest.json](account-manifest.json).
O checksum do arquivo ZIP está em
[pkxd-1.38.4-account-local.zip.sha256](pkxd-1.38.4-account-local.zip.sha256).
Os arquivos internos têm seu próprio `SHA256SUMS`.

Para reproduzir a partir do **metadata original**, com saída em um caminho novo:

```sh
python tools/redirect_lobby_metadata.py global-metadata.dat global-metadata.account-local.dat --include-accounts
```

O [pacote anterior, só de lobby](pkxd-1.38.4-metadata-local.zip) e seu
[manifesto](manifest.json) permanecem como referência da etapa 1.
