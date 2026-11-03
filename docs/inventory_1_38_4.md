# InventoryServiceInitStep e inventário inicial local

O teste no aparelho após a correção de horário/catálogos passou a mostrar
`InventoryServiceInitStep` como etapa pendente. Os mesmos logs identificaram
`backpack` sem resposta e a operação `pet` 16, ainda não implementada.

## Causa da espera

`InventoryServiceInitStep.<>c.<RunStepImplementation>b__2_0`, RVA `0x3288E4C`,
acessa `IServer.get_UserInventory` (slot 15) e verifica se a lista é não nula
e tem `Count > 0`. Em `0x3289004–0x328900C`, lê Count, compara com zero e usa
`cset gt`. A coroutine `MoveNext`, RVA `0x3289024`, espera esse predicado antes
de chamar PlayerInventoryService.Init e publicar InventoryInitializedMessage.

O servidor enviava `p` como IntList vazio. Isso satisfazia a presença das
variáveis na etapa anterior, mas mantinha este predicado falso. O inventário
não é apenas uma lista de IDs: `PlayKids.XD.Inventory.InitInventory`, RVA
`0x2C76EE0`, lê pares consecutivos de ID e quantidade e chama AddItem(id, quantity).
O payload de `p` agora contém tag 6 e esses pares, com int32 big-endian.

## Defaults identificados e política local

Os IDs foram identificados em `Multiplayer.Game.Avatar.AvatarUtils`, TypeDefIndex
5442, e conferidos no construtor estático, RVA `0x2EC9CD4`. A concessão inicial
abaixo é uma decisão do servidor local baseada nesses defaults; não é uma
reconstrução comprovada do inventário de uma conta nova do backend oficial.

| Componente | ID | Slot(s) |
| --- | --- | --- |
| Animação padrão | 4636 | 4 |
| Cabeça | 16 | 5 |
| Rosto | 5 | 6 |
| Base do tronco | 13 | 7 |
| Material do tronco | 272 | 8 |
| Base das pernas | 15 | 9 |
| Material das pernas | 273 | 10 |
| Mãos | 17 | 11, 12 |
| Pés | 59 | 13, 14 |

Os slots de mãos e pés compartilham seus respectivos itens. São nove IDs únicos,
com quantidade 1 de cada. Os defaults de partes 13 e 15 são as constantes
UpperBodyPartBase e LowerBodyPartBase. A roupa `o` usa os 18 slots de ItemSlot;
AvatarUtils.ToItemArray, RVA `0x2EC9914`, aloca uma array de tamanho `0x12`.
Uma aparência já salva permanece prioritária sobre a roupa inicial. Um valor
antigo de roupa completamente vazio é tratado como não inicializado.

Inventário e favoritos são persistidos no SQLite. Na primeira execução desta
versão, contas antigas recebem a inicialização local uma única vez. A migração
adiciona tabelas e preserva UUID, nome, tokens, consentimentos e aparência.
Inventários personalizados já existentes não são sobrescritos. Um marcador de
concessão impede que reiniciar o processo reponha ou multiplique itens.

## Mochila e pets

`BackpackEventId.Favorite = 2`. A inicialização do delegate de favoritos envia
`FavoriteBackpackItemRequest` com Added/Removed vazios, compatível com os dois
bytes `08 02` vistos no log. ToxicBirdBackpackMechanic.SendFavoriteMessage
(`0x30B7B5C`) define esse ID e registra o callback.

A resposta também usa `backpack`, com FavoriteBackpackItemResponse:
EventId=1, Success=2, Failure=3. Success é uma **submensagem oneof**, não um
booleano. Mesmo uma lista vazia exige a presença de Success: os bytes são
`08 02 12 00`. Omitir esse campo deixa a resposta sem resultado selecionado.
SuccessfulFavoriteResponse é construída em OnBackpackResponse (`0x30B71BC`).

Consultas retornam os favoritos atuais. Alterações usam Added=2 e Removed=3,
suportam as formas protobuf packed/unpacked e são persistidas em transação.
Adicionar favorito exige um item pertencente ao jogador autenticado. IDs
inválidos ou não possuídos produzem Failure, com ErrorMessage no campo 1.
Favoritar não concede nem compra itens. Purchase/Remove de mochila continuam
como operações separadas, ainda não implementadas.

O evento de pets com 40 bytes foi identificado pelo log como operação 16.
`ProtobufPetMechanic.GetPetNeedData`, RVA `0x2E06E48`, usa GetPetNeedsRequest:
EventId=1, OwnerId=2. A resposta é PetNeedDataResponse, EventId=21, Needs=2.
Para a conta local sem pets, retorna a lista vazia no evento `pet`, com bytes
`08 15`. Isso não cria pets nem confirma alteração de necessidades.

## Atualização e teste no Termux

Pare o servidor com Ctrl+C e execute:

```sh
cd ~/PKXD-RE
git pull --ff-only
python server.py
```

Mantenha o APK e o metadata que já conectaram ao servidor. Feche completamente
o jogo e abra novamente. Preserve `data/players.sqlite3`; a migração ocorre ao
iniciar o servidor. No console, devem aparecer, quando o cliente pedir os dados:

```text
TCP initial inventory sent entries=9 equippedSlots=18
TCP backpack favorites sent count=0
TCP initial pet list/cache sent count=0 requestId=16
```

Em outra sessão, `python tools/check_local_character.py` confere inventário
não vazio, pares ID/quantidade, favoritos e a consulta de necessidades de pets,
além das verificações anteriores. Ele cria um jogador de diagnóstico.

Os testes automatizados incluem migração de um banco com o esquema anterior,
preservação de sessão e aparência, ausência de concessão duplicada, inventário
personalizado, favoritos persistentes, recusa de itens não possuídos, bytes da
resposta oneof e tráfego TCP completo. A passagem da tela e o carregamento dos
assets de avatar precisam ser confirmados no aparelho. Catálogo de produtos,
compras, mundo, tutorial completo e concessões originais continuam pendentes.

Não é necessário outro arquivo para esta correção: o predicado, as constantes
e os formatos das mensagens já estavam nos arquivos fornecidos.
