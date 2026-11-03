# PK XD — engenharia reversa

## Etapa 3: sala local e estado do personagem para 1.38.4

O servidor inicia contas anônimas e lobby em HTTP `127.0.0.1:8080`, além da
conexão TCP `127.0.0.1:7000` para login e criação do perfil. Salva nome, roupa,
cor de pele e cabelo em SQLite. A versão **1.38.4**, protocolo `0.2.49`, vem
habilitada em [`config/versions.json`](config/versions.json).
Usa Python e biblioteca padrão, sem instalar pacotes pelo pip.

A sala individual agora recebe posição e rotação (`C`), mudanças de camada
(`PL`) e estados temporários do personagem. Responde ao cache de interação,
às listas de veículos próprios/no mundo e à tabela de evolução de pets.
A cena e o ponto de nascimento são carregados pelo próprio APK. O resultado
visual dessa etapa ainda precisa de teste no Android; os contratos e limites
estão em [Mundo e sala local](docs/world_1_38_4.md).

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
python tools/check_local_character.py
```

O diagnóstico cria um jogador de teste e verifica cadastro, login, horário,
catálogos de inicialização, inventário, favoritos, nome, posição/camada da sala
e reconexão.
A alocação exige um token emitido pelas contas locais;
`userToken: "local-test"` deixa de ser um teste válido do servidor completo.

Para usar **Novo jogador** no APK, instale o
[novo metadata de contas + lobby](client/README.md). O pacote antigo alterava
somente o lobby: atualizar o Python não altera o APK já instalado. Não é
necessário enviar o APK inteiro. A configuração de rede será investigada
caso o teste no aparelho apresente bloqueio de HTTP.

Os jogadores ficam em `data/players.sqlite3`, preservado em atualizações do
Git. Faça uma cópia desse arquivo com o servidor parado para guardar as contas.

Para desabilitar a versão, altere `enabled` para `false` em
`config/versions.json` e reinicie o servidor. A requisição nativa informa o
protocolo, então outras builds que compartilhem `0.2.49` não podem ser
distintas por esse pedido sozinho.

Esta etapa oferece uma sala local individual e o perfil persistente.
Inclui respostas de horário, árvores de loja vazias e consultas iniciais de
amigos, pets, NPCs e cache de variáveis. O inventário inicial local contém nove
itens padrão identificados em AvatarUtils; quantidades e favoritos ficam no SQLite.
Os logs enviados do Android confirmaram
cadastro, sessões, alocação e login TCP; a correção das etapas de inicialização
ainda precisa de novo teste no aparelho.
Sala compartilhada entre jogadores, catálogo completo de produtos, casas,
tutorial completo e demais mecânicas continuam pendentes. O teste automatizado
usa um cliente de protocolo; a entrada visual no mundo ainda depende de teste
no Android.
O login TCP verifica a versão do aplicativo, além da verificação de protocolo
no lobby.

[Contratos e diagnóstico de contas/personagem](docs/character_1_38_4.md).
O [estudo da primeira etapa](docs/version_1_38_4.md) permanece como referência histórica.
Veja a [correção das etapas de inicialização](docs/startup_1_38_4.md) e a
[inspeção dos assets enviados](docs/apk-assets-inspection.json).
O [diagnóstico e a correção de InventoryServiceInitStep](docs/inventory_1_38_4.md)
explicam o formato do inventário e a atualização das contas existentes.
A [correção das atualizações de variáveis](docs/variable_updates_1_38_4.md)
documenta a diferença entre os pacotes do cliente e do servidor e os novos
diagnósticos de desconexão.

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
