// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts-upgradeable/token/ERC721/ERC721Upgradeable.sol";
import "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/ReentrancyGuardUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

interface IERC6551Registry {
    function createAccount(
        address implementation,
        bytes32 salt,
        uint256 chainId,
        address tokenContract,
        uint256 tokenId
    ) external returns (address);
}

interface ITokenURIGenerator {
    function generateURI(uint256 tokenId, uint96 dbh, uint96 biomass, bool isAlive) external view returns (string memory);
}

contract BioRigCoreV4 is 
    Initializable, 
    ERC721Upgradeable, 
    AccessControlUpgradeable, 
    PausableUpgradeable, 
    ReentrancyGuardUpgradeable,
    UUPSUpgradeable 
{
    bytes32 public constant VERIFIER_ROLE = keccak256("VERIFIER_ROLE");
    bytes32 public constant UPGRADER_ROLE = keccak256("UPGRADER_ROLE");

    uint256 private _nextTokenId;

    address public erc6551Registry;
    address public erc6551Implementation;
    uint256 public chainId;
    address public bufferPool;
    address public uriGenerator;

    struct TreeStats {
        uint96 dbh;              
        uint96 biomass;          
        uint64 lastUpdated;      
        address tbaAddress;      
        bool isAlive;            
        bytes32 spatialNullifier; 
    }

    mapping(uint256 => TreeStats) private _trees;
    mapping(bytes32 => bool) private _activeNullifiers;

    error InvalidAddress();
    error InvalidTree();
    error TreeIsDead();
    error NullifierInUse();
    error InvalidGrowthData();

    event TreeMinted(uint256 indexed tokenId, address indexed tba, bytes32 indexed spatialNullifier);
    event GrowthUpdated(uint256 indexed tokenId, uint96 newDBH, uint96 newBiomass);
    event TreeMortalityReported(uint256 indexed tokenId, bytes32 releasedNullifier, address tba);
    event URIGeneratorUpdated(address indexed oldGenerator, address indexed newGenerator);
    event BufferPoolUpdated(address indexed oldPool, address indexed newPool);

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    function initialize(
        address _registry,
        address _implementation,
        uint256 _chainId,
        address _bufferPool,
        address _uriGenerator
    ) initializer public {
        if (_registry == address(0) || _implementation == address(0) || _bufferPool == address(0)) revert InvalidAddress();

        __ERC721_init("BioRig Tree", "TREE");
        __AccessControl_init();
        __Pausable_init();
        __ReentrancyGuard_init();
        __UUPSUpgradeable_init();

        erc6551Registry = _registry;
        erc6551Implementation = _implementation;
        chainId = _chainId;
        bufferPool = _bufferPool;
        uriGenerator = _uriGenerator;
        _nextTokenId = 1;

        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(UPGRADER_ROLE, msg.sender);
    }

    function mintTree(
        address planter,
        bytes32 spatialNullifier,
        uint96 initialDBH,
        uint96 initialBiomass
    ) external nonReentrant whenNotPaused onlyRole(VERIFIER_ROLE) returns (uint256) {
        if (planter == address(0)) revert InvalidAddress();
        if (_activeNullifiers[spatialNullifier]) revert NullifierInUse();

        uint256 tokenId = _nextTokenId++;
        
        _activeNullifiers[spatialNullifier] = true;

        bytes32 salt = keccak256(abi.encodePacked(tokenId, planter, spatialNullifier));

        address treeWallet = IERC6551Registry(erc6551Registry).createAccount(
            erc6551Implementation,
            salt,
            chainId,
            address(this),
            tokenId
        );

        _trees[tokenId] = TreeStats({
            dbh: initialDBH,
            biomass: initialBiomass,
            lastUpdated: uint64(block.timestamp),
            tbaAddress: treeWallet,
            isAlive: true,
            spatialNullifier: spatialNullifier
        });
        
        _safeMint(planter, tokenId);

        emit TreeMinted(tokenId, treeWallet, spatialNullifier);
        return tokenId;
    }

    function updateTreeGrowth(
        uint256 tokenId,
        uint96 newDBH,
        uint96 newBiomass
    ) external whenNotPaused onlyRole(VERIFIER_ROLE) {
        TreeStats storage tree = _trees[tokenId];
        
        if (ownerOf(tokenId) == address(0)) revert InvalidTree();
        if (!tree.isAlive) revert TreeIsDead();
        if (newDBH < tree.dbh || newBiomass < tree.biomass) revert InvalidGrowthData();

        tree.dbh = newDBH;
        tree.biomass = newBiomass;
        tree.lastUpdated = uint64(block.timestamp);

        emit GrowthUpdated(tokenId, newDBH, newBiomass);
    }

    function reportMortality(uint256 tokenId) external onlyRole(VERIFIER_ROLE) {
        TreeStats storage tree = _trees[tokenId];
        
        if (ownerOf(tokenId) == address(0)) revert InvalidTree();
        if (!tree.isAlive) revert TreeIsDead();

        tree.isAlive = false;
        _activeNullifiers[tree.spatialNullifier] = false;
        
        emit TreeMortalityReported(tokenId, tree.spatialNullifier, tree.tbaAddress);
    }

    function getTreeStats(uint256 tokenId) external view returns (TreeStats memory) {
        if (ownerOf(tokenId) == address(0)) revert InvalidTree();
        return _trees[tokenId];
    }

    function isNullifierActive(bytes32 spatialNullifier) external view returns (bool) {
        return _activeNullifiers[spatialNullifier];
    }

    function tokenURI(uint256 tokenId) public view override returns (string memory) {
        if (ownerOf(tokenId) == address(0)) revert InvalidTree();
        
        if (uriGenerator != address(0)) {
            TreeStats memory tree = _trees[tokenId];
            return ITokenURIGenerator(uriGenerator).generateURI(tokenId, tree.dbh, tree.biomass, tree.isAlive);
        }
        
        return super.tokenURI(tokenId);
    }

    function setURIGenerator(address _newGenerator) external onlyRole(DEFAULT_ADMIN_ROLE) {
        address oldGenerator = uriGenerator;
        uriGenerator = _newGenerator;
        emit URIGeneratorUpdated(oldGenerator, _newGenerator);
    }

    function setBufferPool(address _newPool) external onlyRole(DEFAULT_ADMIN_ROLE) {
        if (_newPool == address(0)) revert InvalidAddress();
        address oldPool = bufferPool;
        bufferPool = _newPool;
        emit BufferPoolUpdated(oldPool, _newPool);
    }

    function pause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _unpause();
    }

    function _authorizeUpgrade(address newImplementation) internal override onlyRole(UPGRADER_ROLE) {}

    function supportsInterface(bytes4 interfaceId) public view override(ERC721Upgradeable, AccessControlUpgradeable) returns (bool) {
        return super.supportsInterface(interfaceId);
    }
}