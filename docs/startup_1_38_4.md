# Respostas de inicialização após login

Os logs do aparelho confirmaram cadastro anônimo, sessões, alocação e login TCP
com `newCharacter=true`. O cliente recebeu o bootstrap e enviou outros pedidos
que ainda não tinham resposta. A imagem mostrou a lista de inicialização parada
em AcceptanceOfTermsFlowInitStep, ServerTimeServiceInitStep e StoreTreeInitStep.
Isso substitui a hipótese anterior de falha no redirecionamento de contas para
essa tentativa: o fluxo já chegou às contas locais e à conexão de jogo.

No teste seguinte, horário e árvores de loja receberam respostas e a tela
passou a mostrar somente InventoryServiceInitStep. A [correção de inventário](inventory_1_38_4.md)
substitui o inventário vazio por defaults locais identificados no binário e
implementa favoritos e a consulta de necessidades dos pets.

## Atualização no Termux

Pare o servidor com Ctrl+C e execute:

```sh
cd ~/PKXD-RE
git pull --ff-only
python server.py
```

Os logs já confirmaram a conexão do APK ao serviço de contas e lobby; esta
atualização altera somente o servidor. Preserve o APK e o metadata que produziram
esses logs. Feche completamente o jogo e abra novamente após reiniciar o
servidor, para executar de novo os serviços que pedem dados apenas uma vez por
inicialização. Não é necessário apagar contas, banco ou dados do aplicativo.

Em outra sessão, `python tools/check_local_character.py` verifica o servidor.
Além do fluxo anterior, ele agora consulta horário e árvores de loja e confere
IDs/campos das respostas. O diagnóstico cria uma conta de teste.

## Contratos implementados

Todas as respostas abaixo são RoomEvents, opcode 8, após login válido e entrada
na sala. Pedidos antes do login são recusados. Listas vazias representam o estado
atual do servidor local, que ainda não tem operações para adicionar amigos,
comprar pets ou criar NPCs.

| Pedido | Resposta | Conteúdo |
| --- | --- | --- |
| `time`, TimeRequest EventId=0 | `time` | GetCurrentTimeResponse, CurrentTime no campo 2, **segundos Unix** |
| `store_tree`, Get=0, StoreTreeId=2 | `L` | GetStoreTreeResponse: Successful=1, ErrorMessage=2, StoreTree=3 |
| `store_tree`, CheckIds=1, IDs repetidos=2 | `L2` | CheckStoreTreeIdsResponse: Successful=1, ErrorMessage=2 |
| `pet_store_tree`, Get=0, PetStoreTreeId=2 | `PST` | GetPetStoreTreeResponse: Successful=1, ErrorMessage=2, EventId=3, StoreTree=4 |
| `friends`, GetAll=0 | `get_friends_result` | FriendInformationResponse: Successful=1 e listas vazias |
| `npc/fetch-owned`, mensagem vazia | `npc/fetch-owned` | FetchAllOwnedNpcResponse com NpcList vazia |
| `game_variable`, GetCache=3 | `q` | GameVariablesCacheResponse com Variables e States vazios |
| `pet`, List=0 | `pet` | GetPetsResponse, EventId=8, Successful no campo 2, Pets vazios |
| `pet`, GetCache=6 | `pet` | GetPetsCacheResponse, EventId=7, pets/ovos vazios |
| `pet`, GetPetNeedData=16 | `pet` | PetNeedDataResponse, EventId=21, Needs vazios para a conta local sem pets |
| `pet`, GetAllRemotePets=28 | `pet` | GetAllRemotePetsResponse, EventId=36, consulta inicial do próprio jogador |
| `hair_style`, GetInventory=0 | `get_hair_styles` | GetHairStyleInventoryResponse, Successful=1, Inventory vazio |
| `lb`, Info=0 | `lb` | LootBoxInfoResponseMessage, Successful=3, Items vazios |
| `pet`, GetPetDetails=19 | `pet` | PetDetailsResponse, EventId=24, lista vazia |
| `pet`, GetEggDetails=24 | `pet` | EggDetailsResponse, EventId=32, lista vazia |
| `init_day_night`, vazio | `G` | DayNightStateResponse, IsNight=false, SkipInterpolation=true |
| `init_pos`, vazio | `C` | Snapshot vazio de posições remotas, comprimido com DEFLATE raw |
| `fruit`, GetCount=3 | `fruit-quest-count` | GetCountFruitQuestResponse: Count float=1 e Sequence int32=2, ambos zero |
| `matchmaking`, GetLobbyState=2, LobbyType=2 | `matchmaking_lobby_state` | LobbyStateResponseMessage: TimeLeftMillis=1, TimerState=2, LobbyType=3; estado Waiting, preservando o tipo solicitado |
| `hwn`, SecondsToEnd=3 | `hwn` | SpecialEventSecondsToEndResponse: EventId=1 vale 3; Seconds=2 vale zero, sem evento sazonal ativo |
| `referral`, GetLinkInfo=0 | `N` | ReferralLinkResponse: Data=2 presente; Successful=1, ReferralLink=3 vazio, contagens e usuários convertidos vazios |

`Analytics/sessionId` e `Analytics/deviceId` são mensagens de mão única com IDs
brutos. Não precisam de resposta; o servidor não encaminha nem salva esses IDs.
`fetch_events` consulta os eventos ativos; não há um acknowledgement dedicado
no cliente. A sala local não tem eventos de mundo/quests configurados, portanto
não envia notificações de eventos ativos. Isso não implementa essas mecânicas.

O cache de variáveis aceita Owner=-1 para o mundo, zero ou o ID de transporte
local. O C# codifica -1 como varint de dez bytes: o pedido de cache observado com
13 bytes é compatível com `08 03 10 FF FF FF FF FF FF FF FF FF 01`. Alterações de
estado não são confirmadas como se o mundo já estivesse implementado.

StoreTreeData contém Id=1, Version=2, ProductKey=3, Items=4. A versão local é
`local-bootstrap-1`; cada ID é preservado exatamente. Há 18 IDs versionados
extraídos de StoreTreeConstants, incluindo `avatar-store-0_2_49` e
`houses-store-0_2_05`. O catálogo especial de pets usa `eggs-store-0_1_86`.
IDs desconhecidos recebem falha explícita. O objeto StoreTree é sempre enviado,
inclusive na resposta de erro, porque o cliente o acessa antes de notificar a
etapa de inicialização. Os catálogos são locais e vazios: produtos, preços e
compras continuam pendentes; o inventário inicial usa a política local documentada.

As respostas de termos existentes permanecem no evento `Q`, com ação GET/SET.
Agora o console registra o ID do pedido de perfil e a ação retornada para ajudar
a localizar qualquer espera restante. A correção não registra aceitação de
termos nem consentimento de anúncios automaticamente.

## Evidência nativa

| Método | RVA | Verificação |
| --- | --- | --- |
| ToxicBirdTimeMechanic.Install | `0x30392CC` | Resposta registrada no evento `time` |
| ProtobufTimeMechanic.ProcessServerResponse | `0x22B71E0` | Parse de GetCurrentTimeResponse e leitura de CurrentTime |
| CurrentTimeResponse.ctor(long) | `0x30A03C8` | Chama DateTimeOffset.FromUnixTimeSeconds |
| ToxicBirdStoreTreeMechanic.Install | `0x2E93258` | Eventos `L` e `L2` |
| ToxicBirdStoreTreeMechanic.OnStoreTreeServerEvent | `0x2E93610` | Parse de GetStoreTreeResponse/StoreTreeData |
| StoreTreeInitStep.OnStoreTreeReceived | `0x2A08634` | Marca o ID recebido e publica StoreTreeReceivedMessage |
| ToxicBirdPetStoreTreeMechanic.Install | `0x2DF44F0` | Evento `PST` |
| ToxicBirdPetStoreTreeMechanic.OnPetStoreTreeServerEvent | `0x2DF467C` | Parse do DTO especial de pets |
| ToxicBirdServer.ProcessGetFriendsResult | `0x23B685C` | FriendInformationResponse |
| ToxicBirdNpcMechanic.Install / ProcessFetchAllOwned | `0x302BB3C` / `0x302CDAC` | Evento `npc/fetch-owned` e FetchAllOwnedNpcResponse |
| ToxicBirdServer.SendRequestForVariableCache | `0x23B806C` | EventId=3 e Owner no campo 2 |
| ToxicBirdServer.HandleGameVariablesUpdate | `0x23B7D00` | GameVariablesCacheResponse |
| ToxicBirdPetMechanic.Install | `0x1BA65B8` | Resposta no evento `pet` |
| ProtobufPetMechanic.ProcessServerResponse | `0x2E02E78` | Seleção da resposta por PetResponseEventId |

## Arquivos de assets enviados

O usuário identificou os dois arquivos como provenientes de `assets` do APK.
`catalog.json` é Unity Addressables ContentCatalogData: 16.559 IDs internos,
217 tipos de recurso e seis providers. `games.zip` contém 31 bundles UnityFS
de Unity `2021.3.18f1`, com prefabs de frutas e telas finais de minigames.
Todos os 31 nomes de bundle foram encontrados no catálogo. Hashes e inventário
estão em [apk-assets-inspection.json](apk-assets-inspection.json).

Esse catálogo mapeia recursos Unity para carregamento; as árvores StoreTreeData
consultadas pela rede são outro formato. Os arquivos enviados foram preservados,
sem executar ou modificar bundles. Não foram convertidos em produtos ou IDs de
itens sem uma relação comprovada.

## Validação e limite do resultado

Os testes verificam os bytes conhecidos da resposta de horário, a diferença
entre StoreTree campo 3 e PetStoreTree campo 4, IDs de resposta de pets,
ID desconhecido, varint negativo do C#, mensagens vazias válidas e consultas
fora da sequência. Um teste TCP reproduz a sequência de pedidos suportados do
log, confere a ordem dos eventos e que mensagens de analytics não geram respostas.

A execução da tela após esta alteração ainda depende de teste no Android.
As consultas iniciais de `fruit`, `matchmaking`, `hwn` e `referral` agora têm
respostas específicas. O [contrato das quatro consultas](entry_services_1_38_4.md)
registra os métodos nativos, bytes e limites. O cache de `slot_interaction` está
implementado na [sala local](world_1_38_4.md). Isso não implementa missões de
frutas, partidas de minigames, recompensas sazonais ou presentes de indicação.
