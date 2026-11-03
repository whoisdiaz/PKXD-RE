# Contas e personagem — PK XD 1.38.4

O sintoma relatado foi carregamento infinito após **Novo jogador**, sem novas
chamadas ao servidor. Isso não comprova uma causa única. A etapa anterior alterava
somente o lobby e não iniciava a conexão de jogo. Agora há contas locais, TCP e
perfil persistente, com metadata que redireciona também contas. A tela Android
ainda precisa ser testada.

Atualização: os logs posteriores enviados do Android confirmaram o fluxo de
cadastro/sessões/lobby/TCP e identificaram espera por ServerTimeServiceInitStep
e StoreTreeInitStep. A [correção de inicialização](startup_1_38_4.md) implementa
as respostas dessas etapas e consultas iniciais; seu resultado na tela precisa
ser verificado no aparelho.

A etapa seguinte adiciona [sala local, movimento e consultas do mundo](world_1_38_4.md).
O resultado visual após essa atualização ainda precisa de teste no APK.

## Termux

Pare a instância anterior com Ctrl+C e execute:

```sh
cd ~/PKXD-RE
git pull --ff-only
python server.py
```

Padrões: HTTP `127.0.0.1:8080`, TCP `127.0.0.1:7000`, UDP desativado, banco
`data/players.sqlite3`. O caminho padrão do banco independe da pasta atual.
Use `--database CAMINHO` para selecionar outro. Copie o banco com o servidor
parado para guardar as contas; ele é ignorado pelo Git e preservado ao atualizar.

Em outra sessão, `python tools/check_local_character.py` cria um jogador de
diagnóstico e verifica cadastro, login, nome e reconexão. Esse teste verifica o
servidor. Para testar o APK, instale o [novo metadata](../client/README.md).

## HTTP

| Rota | Entrada relevante | Resposta |
| --- | --- | --- |
| `POST /v1/identity/anonymous/sign-up` | Objeto de cadastro/dispositivo | `token` da identidade |
| `POST /v1/auth/sessions` | `identityProvider: "FASTER"`, `credentials: {type: "TOKEN", token}` | `userId`, `sessionId`, `identity`, `identityType`, `authToken` |
| `POST /v1/users/sessions` | `authToken` | `userId`, `sessionId`, `authSessionId`, `userToken`, `countryByIp` |
| `POST /v1/auth/sessions/pkxd/token` | `authToken` | Novo `authToken` do mesmo jogador |
| `GET /v1/auth/sessions/{authToken}` | Token no caminho | `userId`, `identityType`, `identityKey` |
| `GET /v1/users/identities` | `Authorization: Bearer {userToken}` | DTO de identidades locais |
| `POST /lobby/allocation` | Token local, protocolo `0.2.49`, `isPrivate: false` | Destino TCP |

As rotas e DTOs foram conferidos no binário ARM64 enviado. RVAs dos métodos do
FasterClient: cadastro `0x2E17880`, autenticação `0x2E179B0`, sessão do jogador
`0x2E17A48`, consulta `0x2E17AE0`, identidades `0x2E17B88`, renovação `0x2E17C20`.
O fluxo `Faster.<CreateAuthSessionAsync>d__22.MoveNext` (`0x2E153E4`) e o
construtor de credenciais (`0x2E5B9AC`) fixam `FASTER` e `TOKEN`.
O request genérico (`0x1DE841C`) monta `Authorization` com `Bearer `.
Erros usam os campos de `FasterErrorResponse`: `statusCode`, `status`, `description`.

São credenciais próprias do servidor local. Não há comunicação com Faster
oficial, importação de contas, cadastro por e-mail ou login Google/Firebase.
Identidade, autenticação e jogador têm tokens separados e vinculados à conta.
O banco guarda apenas hashes SHA-256; tokens inválidos/expirados recebem 401.
Validades locais: identidade dez anos, autenticação 30 dias, jogador sete dias.
Esses prazos são decisões locais; não foram recuperados do serviço original.
As contas usam UUID, tipo `anonymous` e país padrão local `BR`.

## Transporte e perfil

`ToxicBirdClient.SendMessage` (`0x35A2464`) e `ReceiveMessage` (`0x35A30CC`)
usam prefixo de **quatro bytes big-endian**: tamanho sem o próprio prefixo.
`FeatherSerializer.Serialize` (`0x359FB04`) e `Deserialize` (`0x35A0244`)
definem os opcodes. Eventos têm um byte de tamanho do nome ASCII, nome e payload.

| Mensagem | Formato após o prefixo TCP |
| --- | --- |
| Connect | `03` |
| Reconnect | `04` + chave ASCII restante |
| Connected | `03` + player ID int32 BE + chave ASCII restante |
| Event | `05` + tamanho/nome ASCII + payload |
| JoinedRoom, sucesso | `06 01` + room ID int32 BE + IDs int32 BE dos presentes |
| RoomEvent | `08` + tamanho/nome ASCII + payload |
| Ping / Pong | `01` / `02` |

O ID de transporte difere do UUID persistente. Reconnect exige login com token
válido; a chave de conexão sozinha não recupera uma conta. O servidor aceita
frames fragmentados, limita a 256 KiB e fecha pacotes inválidos/fora de sequência.

O evento global `login` contém LoginRequest: UserToken 1, ReferralUserId 2,
AppVersion 3. LoginResponse: Successful 1, ErrorMessage 2, IsNew 3,
IsOnboarding 4, OnBoardingCompletedSteps 5. Token e appVersion `1.38.4` são
verificados. Como regra local inicial, novo perfil permanece ativo até o primeiro
nome; nenhum passo de tutorial é enviado como ficticiamente concluído.

Cada conexão possui sala individual contendo o próprio jogador. A sala agora
mantém posição, camada e estado transitório, conforme [etapa 3](world_1_38_4.md).
Nas notificações servidor → cliente, `tbulv` leva player ID int32 BE, tamanho da
chave int32 BE, chave ASCII e valor tipado. Na escrita cliente → servidor, o ID
é omitido: o dono vem da conexão autenticada. Isso foi corrigido ao comparar
UserVariable.Serialize (`0x3A86404`) com Deserialize (`0x3A86830`); veja a
[correção de variáveis](variable_updates_1_38_4.md).
Os serializadores de valores são `0x359C240` / `0x359C8D4`.
Tags usadas: string 1, int32 BE 2, byte 3, ByteList 5, IntList 6.
O formato de `tbulvb` é diferente e não é usado aqui.

HasReceivedAllImportantVariables (`0x23BDCEC`) consulta `p,o,wa,j,s,i,hs`.
O bootstrap envia inventário com pares de ID/quantidade e os 18 slots de roupa
padrão, saldo zero, RGB local padrão, casa vazia, slot byte zero e cabelo zero,
além de UUID e nome. Os IDs padrão do avatar vieram de AvatarUtils; a política
de concessão é local, conforme a [correção de inventário](inventory_1_38_4.md).
O construtor ToxicBirdRemotePlayerServerState (`0x2DE7F54`) confirma `s` como
ByteList de HouseData e `i` como ByteVariable; `hs` é IntVariable.

SendEquipMessage (`0x23B5A40`) emite RoomEvent `equip`, com EquipRequest:
Items 1 (int32 repetido), SkinColor 2 (Color: R/G/B 1/2/3), HairModel 3,
HairStyle 4. O servidor salva roupa/RGB/cabelo em uma transação e devolve
alterações de variáveis. Aceita escritas diretas válidas de `j,o,hs`, verificando
o ID do próprio jogador. Carteira, inventário e permissões não são editáveis
por esse caminho. Limites locais: até 32 IDs entre zero e um milhão, RGB de
0 a 255; não há validação contra catálogo nem compras nesta etapa.

`profile_update` é o RoomEvent do perfil. Pedidos implementados:

| ProfileEventId | Resposta |
| --- | --- |
| 0 SetNickname, nome campo 2 | `set_name_result`: Name 1, ErrorMessage 2 |
| 12 GetDefaultNickname | `default_nickname_result`: DefaultNickname 1 |
| 10 GetAccountCreatedDate | `account_created_date`: Successful 1, ErrorMessage 2, Date 3 |
| 4 / 5 Set/GetLegalInfo | `Q`, ação `SET`/`GET`; consentimento só em pedido explícito |
| 6 / 7 Set/GetOpenChatEnabled | `R`, preferência persistida; chat não implementado |

As inscrições aparecem em ToxicBirdProfileMechanic.Install (`0x2DF99BC`).
Date usa protobuf int64 em milissegundos Unix: WriteTo (`0x1CF3D50`) chama
WriteInt64, e o construtor (`0x22B9B7C`) converte milissegundos Unix para UTC.
Nome: regra local de 2–24 caracteres visíveis, NFC e unicidade sem distinguir
maiúsculas. Primeiro nome confirma o perfil; repetir o mesmo pedido é permitido.
Troca posterior de nome é outra funcionalidade. Nenhum termo é automaticamente
aceito; a versão mais recente fica vazia enquanto não existir um documento local.

## Validação e limites

`python -m unittest discover -s tests -v` cobre valores binários conhecidos,
protobuf truncado e campos repetidos, frames fragmentados, sessões inválidas e
expiradas, versão incorreta, fluxo HTTP/TCP, persistência e reconexão, colisões
de nome e recusa de escrita no saldo ou em outro jogador.

O novo metadata altera apenas os três literais do [manifesto](../client/account-manifest.json).
Atualizar só o Python não altera o APK. Bloqueio de HTTP no Android, token
oficial armazenado, assets de 2023 indisponíveis ou outros serviços pendentes
precisam ser identificados no aparelho. Os testes do servidor não comprovam
que o carregamento na tela foi resolvido.

Ficam para próximas partes: salas compartilhadas/sincronização entre jogadores,
casas, catálogo completo de produtos,
tutorial completo, economia, compras e contas por e-mail. Eventos ausentes são
registrados como `unsupported`; não recebem sucesso genérico.
