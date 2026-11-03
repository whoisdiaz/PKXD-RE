# Consultas locais de entrada — PK XD 1.38.4

Os logs do Android mostravam `fruit` (2 bytes), `matchmaking` (4 bytes), `hwn`
(2 bytes) e `referral` (corpo vazio) sem tratamento após o login. Esta alteração
implementa quatro consultas desses domínios em `StartupServices`, usando os
serializadores e leitores da lib ARM64 fornecida. São respostas reais de sala,
opcode 8, depois da autenticação e da entrada na sala.

## Contratos recuperados

| Consulta | Pedido Protobuf em hex | Evento de resposta | Resposta local em hex |
| --- | --- | --- | --- |
| Contagem de missões de frutas | `08 03` | `fruit-quest-count` | mensagem vazia |
| Estado da fila, exemplo FreezingFun (3) | `08 02 10 03` | `matchmaking_lobby_state` | `18 03` |
| Segundos restantes do evento sazonal | `08 03` | `hwn` | `08 03` |
| Informação de indicação | mensagem vazia | `N` | `12 04 08 01 1A 00` |

`GetCountFruitQuestResponse` contém Count **float** no campo 1 e Sequence int32
no campo 2. Não contém EventId. Ambos são zero pela política local sem missões
configuradas; o Protobuf omite esses valores padrão. A resposta vazia ainda é
enviada com seu envelope `fruit-quest-count`.

`LobbyStateResponseMessage` contém TimeLeftMillis int64=1, TimerState=2 e
LobbyType=3. O estado local é Waiting=0 e o tempo é zero. O servidor preserva o
tipo solicitado entre 0 e 6, pois o cliente seleciona o callback usando esse
campo. Nenhuma partida é alocada por esta consulta. JoinLobby/LeaveLobby de
minigames continuam sem implementação.

`SpecialEventSecondsToEndResponse` usa SpecialEventType.SecondsToEnd=3 no
campo 1 e Seconds int64 no campo 2. Zero representa a política local sem evento
sazonal ativo. Só essa consulta de `hwn` foi implementada nesta alteração.

`ReferralLinkResponse.Data` precisa existir. O campo Data=2 contém Successful=1
e um objeto ReferralLink vazio no campo 3. A consulta é concluída com URL/status
vazios, contagens zero e nenhuma conversão; não cria links nem concede presentes.
ClaimSenderGift e CreateUserReferralLink continuam sem implementação.

O log antigo informa apenas nome/tamanho desses pedidos, exceto o corpo vazio
de indicação. Os IDs e campos acima vêm dos métodos nativos; não houve captura
dos corpos reais desses três pedidos no aparelho. Compatibilidade com o
contrato não prova que todos eram dependências obrigatórias da cena.

## Evidência na lib ARM64

| Método | RVA | Relação com o contrato |
| --- | --- | --- |
| ToxicBirdFruitQuestMechanic.SendGetQuestCount | `0x2DEE9B4` | Envia `fruit`, EventId=3 |
| ToxicBirdFruitQuestMechanic.Install | `0x2DEDA60` | Registra `fruit-quest-count` |
| ToxicBirdFruitQuestMechanic.ProcessFruitQuestCount | `0x2DEDF48` | Lê Count float e Sequence int32, invoca callback |
| ProtobufMatchmakingMechanic.ForceLobbyStateUpdate | `0x3041BE4` | EventId=2, LobbyType no campo 2 |
| ToxicBirdMatchmakingMechanic.Install | `0x3029704` | Registra `matchmaking_lobby_state` |
| ProtobufMatchmakingMechanic.HandleLobbyStateUpdatedEvent | `0x3029B04` | Callback indexado pelo LobbyType recebido |
| LobbyStateUpdatedResponse.ctor | `0x3042274` | Converte TimeLeftMillis para segundos |
| ToxicBirdSpecialEventMechanic.SendGetSecondsToEnd | `0x3035548` | Envia `hwn`, EventId=3 |
| ToxicBirdSpecialEventMechanic.Install | `0x30351F0` | Registra resposta `hwn` |
| ToxicBirdSpecialEventMechanic.OnSpecialEventServerResponse | `0x30362CC` | Faz dispatch e lê Seconds do DTO |
| ToxicBirdServer.GetReferralInfo | `0x23BF7C0` | Envia `referral`, EventId=0 omitido |
| ToxicBirdServer.InstallReferralBehavior | `0x23B523C` | Registra resposta `N` |
| ToxicBirdServer.HandleGetLinkInfoResponse | `0x23BF260` | Acessa Data e produz o callback de informação |

Os nomes exatos dos métodos estão no dump e no índice publicados. Os RVAs
referem-se à lib de dezembro de 2023 fornecida pelo usuário.

## Validação e atualização

Os testes usam bytes literais dos contratos, cobrem os sete tipos de fila,
tipos inválidos, mensagens truncadas e operações ainda sem implementação.
O teste HTTP/TCP de integração autentica a conta, entra na sala, intercala as
quatro consultas com analytics e movimento e verifica as respostas, o Pong e
a preservação da conta/inventário. Pedidos anteriores ao login são recusados.

`python tools/check_local_character.py` também verifica as quatro respostas
contra o processo do servidor. A validação do processo inclui reiniciar com o
mesmo banco temporário e conferir que UUID e nome continuam persistidos.

Para atualizar no Termux, pare o servidor com Ctrl+C:

```sh
cd ~/PKXD-RE &&
git pull --ff-only &&
python server.py
```

Feche e abra o jogo novamente para refazer as consultas de inicialização.
A atualização usa o APK, metadata e banco existentes.

Essas respostas completam consultas antes ignoradas. A entrada visual no mundo
e a exibição do personagem ainda não foram confirmadas no Android. Não há
evidência nova de falha ou funcionamento dos links do pkxd-bucket nesta mudança.
