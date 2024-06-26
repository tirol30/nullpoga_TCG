from __future__ import annotations
from random import choice
from npg_monte_carlo_tree_search.istate import IState
from typing import List, Optional, Final, Union, Any, Tuple, Literal
import copy
from enum import Enum
from gameutils.monster_cards import MonsterCard
from gameutils.spell_cards import SpellCard
from gameutils.nullpoga_system import instance_card
from dataclasses import dataclass, field
import uuid
from uuid import UUID
from itertools import zip_longest

LENGTH: Final[int] = 3
HEIGHT: Final[int] = 3
WIDTH: Final[int] = 3

DECK_1: Final = [7, 5, 2, 1, 4, 6, 7, 5, 1, 4, 3, 3, 6, 2]
DECK_2: Final = [4, 1, 7, 5, 5, 7, 6, 3, 4, 1, 3, 6, 2, 2]


class NullPoGaPiece:
    summon_phase_actions: list[Action]

    def __init__(self, deckcards: List[int]):
        self.turn_count = 0
        self.player_id: UUID = uuid.uuid4()
        # デッキの状態(シャッフルはしないので、シャッフルしてから渡す)
        self.deck_cards: List[Union[MonsterCard, SpellCard]] = [instance_card(card_no) for card_no in deckcards]
        self.plan_deck_cards: List[Union[MonsterCard, SpellCard]] = [instance_card(card_no) for card_no in deckcards]
        # 手札
        self.hand_cards: List[Union[MonsterCard, SpellCard]] = []
        self.plan_hand_cards: List[Union[MonsterCard, SpellCard]] = []
        # 場の札 memo:場の札。5レーンのため。
        self.zone = Zone()
        self.plan_zone = Zone()
        # フェイズも管理。
        self.phase = PhaseKind.SPELL_PHASE
        self.plan_mana = 0
        self.mana = 0  # 相手のマナに干渉するカードを考えるためにplanと分けた

        self.spell_phase_actions: List[Action] = []
        self.summon_phase_actions: List[Action] = []
        self.activity_phase_actions: List[Action] = []

    def legal_actions(self) -> List[Action]:
        if self.phase == PhaseKind.SPELL_PHASE:
            spell_phase_actions: List[Union[Action]] = [
                Action(action_type=ActionType.CAST_SPELL, action_data=ActionData(spell_card=card)) for card in
                self.plan_hand_cards if
                isinstance(card, SpellCard) and card.mana_cost <= self.mana]
            spell_phase_actions.append(Action(action_type=ActionType.SPELL_PHASE_END))
            # メモ：スペルの取れる選択肢の数だけactionsは増えるのでspell実装し始めたらそうする
            return spell_phase_actions
        elif self.phase == PhaseKind.SUMMON_PHASE:
            # プレイ可能なモンスターカードをフィルタリング
            possible_monster_cards = [
                card for card in self.plan_hand_cards
                if isinstance(card, MonsterCard) and card.mana_cost <= self.plan_mana
            ]
            # カードを配置可能なフィールドの位置を見つける
            empty_field_positions = [
                i for i, sd in enumerate(self.plan_zone.standby_field)
                if sd is None
            ]
            # 可能な組み合わせを生成
            combinations = [
                Action(action_type=ActionType.SUMMON_MONSTER, action_data=ActionData(index=position, monster_card=card))
                for card in possible_monster_cards
                for position in empty_field_positions
            ]
            combinations.append(Action(action_type=ActionType.SUMMON_PHASE_END))
            return combinations
        elif self.phase == PhaseKind.ACTIVITY_PHASE:
            combinations = []
            for i in range(len(self.zone.battle_field)):
                if self.zone.battle_field[i] and self.zone.battle_field[i].card.can_act:
                    card = self.zone.battle_field[i].card
                    combinations.append(
                        Action(action_type=ActionType.MONSTER_ATTACK, action_data=ActionData(monster_card=card)))
                    if not self.zone.battle_field[i - 1]:
                        combinations.append(
                            Action(action_type=ActionType.MONSTER_MOVE, action_data=ActionData(move_direction="left")))
                    if not self.zone.battle_field[i + 1]:
                        combinations.append(
                            Action(action_type=ActionType.MONSTER_MOVE, action_data=ActionData(move_direction="right")))
            combinations.append(Action(action_type=ActionType.ACTIVITY_PHASE_END))
            return combinations

    def select_plan_action(self, action: Action):
        if Action.action_type == ActionType.CAST_SPELL:
            # 未実装
            pass
        elif Action.action_type == ActionType.SPELL_PHASE_END:
            self.phase = PhaseKind.SUMMON_PHASE
            # スペル使用未実装
            # 進軍フェイズはスペルフェイズ終了時に処理してしまう
            self.move_forward(self.plan_zone)

        elif Action.action_type == ActionType.SUMMON_MONSTER:
            self.summon_phase_actions.append(action)
            self.plan_mana -= action.action_data.monster_card.mana_cost
            self.plan_zone.standby_field[action.action_data.index] = action.action_data.monster_card
            # 手札から召喚したモンスターを削除(削除したい要素以外を残す)
            self.plan_hand_cards = [card for card in self.plan_hand_cards if
                                    card.uniq_id != action.action_data.monster_card.uniq_id]

        elif Action.action_type == ActionType.SUMMON_PHASE_END:
            self.phase = PhaseKind.ACTIVITY_PHASE
        elif Action.action_type == ActionType.MONSTER_ATTACK:
            self.activity_phase_actions.append(action)
            for i, slt in enumerate(self.plan_zone.battle_field):
                if slt.card.uniq_id == action.action_data.monster_card.uniq_id:
                    slt.card.can_act = False
                    break
        elif Action.action_type == ActionType.MONSTER_MOVE:
            self.activity_phase_actions.append(action)
            for i, slt in enumerate(self.plan_zone.battle_field):
                if slt.card and slt.card.uniq_id == action.action_data.monster_card.uniq_id:
                    slt.card.can_act = False
                    if action.action_data.move_direction == "right" and i + 1 < len(self.plan_zone.battle_field):
                        self.plan_zone.battle_field[i + 1].card = slt.card
                        slt.card = None
                    elif action.action_data.move_direction == "left" and i - 1 >= 0:
                        self.plan_zone.battle_field[i - 1].card = slt.card
                        slt.card = None
                    break
        elif Action.action_type == ActionType.ACTIVITY_PHASE_END:
            self.phase = PhaseKind.END_PHASE

    @staticmethod
    def move_forward(zone: Zone):
        for i, sb in enumerate(zone.standby_field):
            if sb and not zone.battle_field[i].card:
                sb.can_act = False
                zone.battle_field[i].card = sb


class State(IState):

    def __init__(self, pieces: Optional[List[int]] = None, enemy_pieces: Optional[List[int]] = None):
        self.pieces: Optional[NullPoGaPiece] = pieces if pieces is not None else NullPoGaPiece(DECK_1)
        self.enemy_pieces: Optional[NullPoGaPiece] = enemy_pieces if enemy_pieces is not None else NullPoGaPiece(DECK_2)

    def next(self, action: int) -> State:
        pieces = copy.deepcopy(self.pieces)
        actions = pieces.legal_actions()
        pieces.select_plan_action(actions[action])
        if pieces.phase == PhaseKind.END_PHASE:
            if self.enemy_pieces == PhaseKind.END_PHASE:
                e_pieces = copy.deepcopy(self.enemy_pieces)
                # 実際に処理する必要がある
                self.execute_plan(pieces, e_pieces)
                return State(e_pieces, pieces)
            else:
                return State(self.enemy_pieces, pieces)

        else:
            return State(pieces, self.enemy_pieces)

    def execute_plan(self, pieces: NullPoGaPiece, e_pieces: NullPoGaPiece):
        # スペルフェイズ未実装
        # 進軍フェイズ
        pieces.move_forward(pieces.zone)
        e_pieces.move_forward(e_pieces.zone)
        # summonフェイズ
        self.execute_summon(pieces, e_pieces)

    @staticmethod
    def execute_summon(pieces: NullPoGaPiece, e_pieces: NullPoGaPiece):
        for my_act, e_act in zip_longest(pieces.summon_phase_actions, e_pieces.summon_phase_actions):
            if my_act and not pieces.zone.standby_field[my_act.action_data.index]:
                pieces.zone.standby_field[my_act.action_data.index] =

    def legal_actions(self) -> List[int]:
        return [i for i in range(HEIGHT * WIDTH) if self.pieces[i] == 0 and self.enemy_pieces[i] == 0]

    def random_action(self) -> int:
        return choice(self.legal_actions())

    @staticmethod
    def pieces_count(pieces: List[int]) -> int:
        return pieces.count(1)

    def is_lose(self) -> bool:
        dy = [0, 1, 1, -1]
        dx = [1, 0, 1, -1]

        for y in range(HEIGHT):
            for x in range(WIDTH):
                for k in range(4):
                    lose = True
                    ny, nx = y, x
                    for i in range(LENGTH):
                        if ny < 0 or ny >= HEIGHT or nx < 0 or nx >= WIDTH:
                            lose = False
                            break
                        if self.enemy_pieces[ny * WIDTH + nx] == 0:
                            lose = False
                            break
                        ny += dy[k]
                        nx += dx[k]
                    if lose:
                        return True

        return False

    def is_draw(self) -> bool:
        return self.pieces_count(self.pieces) + self.pieces_count(self.enemy_pieces) == HEIGHT * WIDTH

    def is_done(self) -> bool:
        return self.is_lose() or self.is_draw()

    def is_first_player(self) -> bool:
        return self.pieces_count(self.pieces) == self.pieces_count(self.enemy_pieces)

    def __str__(self) -> str:
        ox = ('o', 'x') if self.is_first_player() else ('x', 'o')
        ret = ""
        for i in range(HEIGHT * WIDTH):
            if self.pieces[i] == 1:
                ret += ox[0]
            elif self.enemy_pieces[i] == 1:
                ret += ox[1]
            else:
                ret += '-'
            if i % WIDTH == WIDTH - 1:
                ret += '\n'
        return ret


class Zone:
    def __init__(self):
        # 自分から見ての5列の場をフィールドとして初期化
        self.battle_field = [Slot() for _ in range(5)]
        self.standby_field: List[Optional[MonsterCard]] = [None, None, None, None, None]

    def set_battle_field_card(self, index: int, card: MonsterCard):
        if 0 <= index < len(self.battle_field):
            self.battle_field[index].set_card(card)

    def set_standby_field_card(self, index: int, card: MonsterCard):
        if 0 <= index < len(self.standby_field):
            self.standby_field[index] = card

    def remove_battle_field_card(self, index: int):
        if 0 <= index < len(self.battle_field):
            self.battle_field[index].remove_card()

    def remove_standby_field_card(self, index: int):
        if 0 <= index < len(self.standby_field):
            self.standby_field[index] = None

    def gen_summon_combinations(self, m_card: MonsterCard) -> List[Tuple[int, MonsterCard]]:
        m_combinations = []
        for i in range(len(self.standby_field)):
            if self.standby_field[i] is None:
                combination = self.standby_field.copy()
                combination[i] = m_card
                m_combinations.append((i, m_card))
        return m_combinations


class FieldStatus(Enum):
    NORMAL = "Normal"
    WILDERNESS = "Wilderness"  # 荒野状態などの他の状態


class Slot:
    __slots__ = ['status', 'card']

    def __init__(self):
        self.status: FieldStatus = FieldStatus.NORMAL
        self.card: Optional[MonsterCard] = None  # このフィールドに置かれているカード

    def set_card(self, card: MonsterCard):
        self.card = card

    def remove_card(self):
        self.card = None

    def set_wild(self):
        self.status = FieldStatus.WILDERNESS


class PhaseKind(Enum):
    SPELL_PHASE = "SPELL_PHASE"
    SUMMON_PHASE = "SUMMON_PHASE"
    ACTIVITY_PHASE = "ACTIVITY_PHASE"
    END_PHASE = "END_PHASE"


class ActionType(Enum):
    CAST_SPELL = "CAST_SPELL"
    SUMMON_MONSTER = "SUMMON_MONSTER"
    MONSTER_ATTACK = "MONSTER_ATTACK"
    MONSTER_MOVE = "MONSTER_MOVE"
    SPELL_PHASE_END = "SPELL_PHASE_END"
    SUMMON_PHASE_END = "SUMMON_PHASE_END"
    ACTIVITY_PHASE_END = "ACTIVITY_PHASE_END"


@dataclass
class Action:
    action_type: ActionType
    action_data: Optional[ActionData] = None  # 未定


@dataclass
class ActionData:
    index: Optional[int] = field(default=None)
    move_direction: Optional[Literal["right", "left"]] = field(default=None)
    monster_card: Optional[MonsterCard] = field(default=None)
    spell_card: Optional[SpellCard] = field(default=None)
